"""
Source ingestion: get the raw material into object storage in a usable form.

Audio and video are normalised to 16 kHz mono PCM WAV before storage, because
that is what every speech-to-text backend wants and doing it once at ingest
keeps the extraction path simple. Documents are stored as-is.

Storage goes through ``ObjectStore``, so this works against local disk or R2
without the caller knowing which.
"""

import logging
import os
import tempfile
import time
import uuid
from typing import Optional

import ffmpeg
import yt_dlp

from backend.env import load_environment
from backend.services.storage import ObjectStore, get_object_store

logger = logging.getLogger(__name__)

load_environment()


class IngestionService:
    """Normalises and stores uploaded sources, returning provenance metadata."""

    def __init__(self, store: Optional[ObjectStore] = None):
        self.store = store or get_object_store()

    def _convert_to_azure_wav(self, input_path: str, output_path: str):
        """
        Converts audio/video to PCM WAV, 16000Hz, Mono, 16-bit.
        """
        logger.info(f"Normalizing audio: {input_path} -> {output_path}")
        try:
            (
                ffmpeg
                .input(input_path)
                .output(output_path, acodec='pcm_s16le', ac=1, ar='16000')
                .overwrite_output()
                .run(quiet=True, capture_stdout=True, capture_stderr=True)
            )
        except ffmpeg.Error as e:
            logger.error(f"FFmpeg error: {e.stderr.decode() if e.stderr else str(e)}")
            raise

    def _store_file(self, file_path: str, object_key: str) -> str:
        """Store a file and return the key that identifies it."""
        logger.info("Storing source object: %s", object_key)
        return self.store.put_file(file_path, object_key)

    def _generate_metadata(self, file_id, user_id, file_url, file_name, file_type, status="COMPLETED"):
        return {
            "id": file_id,
            "user_id": user_id,
            "fileURL": file_url,
            "fileName": file_name,
            "fileType": file_type,
            "status": status,
            "progress": 100 if status == "COMPLETED" else 0,
            "created_at": time.time()
        }

    def process_youtube(self, url: str, user_id: str) -> dict:
        """
        1. Download Audio
        2. Convert to Azure WAV
        3. Store the normalised audio
        4. Return Metadata
        """
        file_id = str(uuid.uuid4())
        logger.info(f"Processing YouTube: {url} (ID: {file_id})")

        with tempfile.TemporaryDirectory() as temp_dir:
            # 1. Download
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': os.path.join(temp_dir, '%(id)s.%(ext)s'),
                'quiet': True,
                'no_warnings': True,
            }
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    downloaded_path = ydl.prepare_filename(info)
                    video_title = info.get('title', 'YouTube Video')

                # 2. Convert
                wav_filename = f"{file_id}.wav"
                wav_path = os.path.join(temp_dir, wav_filename)
                self._convert_to_azure_wav(downloaded_path, wav_path)

                # 3. Upload
                storage_key = f"uploads/{wav_filename}"
                self._store_file(wav_path, storage_key)

                # 4. Metadata
                return self._generate_metadata(
                    file_id=file_id,
                    user_id=user_id,
                    file_url=storage_key,
                    file_name=video_title,
                    file_type="YOUTUBE"
                )
            except Exception as e:
                logger.error(f"YouTube processing failed: {e}")
                return self._generate_metadata(file_id, user_id, "", "Unknown", "YOUTUBE", status="FAILED")

    def process_audio_upload(self, file_path: str, user_id: str, original_name: str) -> dict:
        """
        1. Convert to Azure WAV
        2. Store the normalised audio
        3. Return Metadata
        """
        file_id = str(uuid.uuid4())
        logger.info(f"Processing Audio Upload: {original_name} (ID: {file_id})")

        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                # 1. Convert
                wav_filename = f"{file_id}.wav"
                wav_path = os.path.join(temp_dir, wav_filename)
                self._convert_to_azure_wav(file_path, wav_path)

                # 2. Upload
                storage_key = f"uploads/{wav_filename}"
                self._store_file(wav_path, storage_key)

                return self._generate_metadata(
                    file_id=file_id,
                    user_id=user_id,
                    file_url=storage_key,
                    file_name=original_name,
                    file_type="AUDIO"
                )
            except Exception as e:
                logger.error(f"Audio processing failed: {e}")
                import traceback
                traceback.print_exc()
                return self._generate_metadata(file_id, user_id, "", original_name, "AUDIO", status="FAILED")

    def _delete_object(self, object_key: str):
        """Remove a stored object. Used to drop the source video once audio is extracted."""
        logger.info("Deleting stored object: %s", object_key)
        self.store.delete(object_key)

    def process_video_upload(self, file_path: str, user_id: str, original_name: str) -> dict:
        """
        1. Store the source video
        2. Extract Audio -> Azure WAV
        3. Store the WAV
        4. Drop the source video
        5. Return Metadata (pointing to Audio)
        """
        file_id = str(uuid.uuid4())
        logger.info(f"Processing Video Upload: {original_name} (ID: {file_id})")

        video_key = f"uploads/{file_id}_video{os.path.splitext(original_name)[1]}"

        try:
            # 1. Upload Video
            self._store_file(file_path, video_key)
            
            with tempfile.TemporaryDirectory() as temp_dir:
                # 2. Convert/Extract
                wav_filename = f"{file_id}.wav"
                wav_path = os.path.join(temp_dir, wav_filename)
                self._convert_to_azure_wav(file_path, wav_path)

                # 3. Upload Audio
                audio_key = f"uploads/{wav_filename}"
                self._store_file(wav_path, audio_key)

                # 4. Delete Video
                self._delete_object(video_key)

                return self._generate_metadata(
                    file_id=file_id,
                    user_id=user_id,
                    file_url=audio_key,
                    file_name=original_name,
                    file_type="VIDEO"
                )
        except Exception as e:
            logger.error(f"Video processing failed: {e}")
            # Attempt cleanup if video was uploaded
            try:
                self._delete_object(video_key)
            except Exception:
                logger.debug("Could not clean up partial video upload %s", video_key)
            return self._generate_metadata(file_id, user_id, "", original_name, "VIDEO", status="FAILED")

    def process_document(self, file_path: str, user_id: str, original_name: str, doc_type: str) -> dict:
        """
        Handles PDF, SLIDES (PPTX), MD.
        1. Store the document as-is
        2. Return Metadata
        """
        file_id = str(uuid.uuid4())
        logger.info(f"Processing Document ({doc_type}): {original_name} (ID: {file_id})")
        
        try:
            # 1. Upload
            # Preserve extension or just use ID? Using ID to avoid collisions, keeping extension
            ext = os.path.splitext(original_name)[1]
            storage_key = f"documents/{file_id}{ext}"
            self._store_file(file_path, storage_key)

            return self._generate_metadata(
                file_id=file_id,
                user_id=user_id,
                file_url=storage_key,
                file_name=original_name,
                file_type=doc_type
            )
        except Exception as e:
            logger.error(f"Document processing failed: {e}")
            return self._generate_metadata(file_id, user_id, "", original_name, doc_type, status="FAILED")
