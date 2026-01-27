import os
import uuid
import time
import logging
import tempfile
import boto3
from botocore.config import Config
import yt_dlp
import ffmpeg
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

class IngestionService:
    def __init__(self):
        self._setup_r2()

    def _setup_r2(self):
        """Initialize Cloudflare R2 client with SigV4."""
        self.r2_endpoint = os.getenv("R2_ENDPOINT_URL")
        self.r2_key = os.getenv("R2_ACCESS_KEY_ID")
        self.r2_secret = os.getenv("R2_SECRET_ACCESS_KEY")
        self.r2_bucket = os.getenv("R2_BUCKET_NAME")

        if self.r2_endpoint and self.r2_key and self.r2_secret:
            self.s3_client = boto3.client(
                service_name='s3',
                endpoint_url=self.r2_endpoint,
                aws_access_key_id=self.r2_key,
                aws_secret_access_key=self.r2_secret,
                region_name='auto',
                config=Config(signature_version='s3v4')
            )
        else:
            logger.warning("R2 credentials missing. Uploads will fail.")

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

    def _upload_to_r2(self, file_path: str, object_key: str) -> str:
        """
        Uploads file to R2 and returns the key.
        """
        logger.info(f"Uploading to R2: {object_key}")
        self.s3_client.upload_file(file_path, self.r2_bucket, object_key)
        # Construct a public or presigned URL if needed, but for now returning key/ID
        # usually R2 public URL is https://<bucket>.<account>.r2.cloudflarestorage.com/<key>
        # or custom domain. For this backend, the key might be enough.
        return object_key 

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
        3. Upload to R2
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
                r2_key = f"uploads/{wav_filename}"
                self._upload_to_r2(wav_path, r2_key)

                # 4. Metadata
                return self._generate_metadata(
                    file_id=file_id,
                    user_id=user_id,
                    file_url=r2_key,
                    file_name=video_title,
                    file_type="YOUTUBE"
                )
            except Exception as e:
                logger.error(f"YouTube processing failed: {e}")
                return self._generate_metadata(file_id, user_id, "", "Unknown", "YOUTUBE", status="FAILED")

    def process_audio_upload(self, file_path: str, user_id: str, original_name: str) -> dict:
        """
        1. Convert to Azure WAV
        2. Upload to R2
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
                r2_key = f"uploads/{wav_filename}"
                self._upload_to_r2(wav_path, r2_key)

                return self._generate_metadata(
                    file_id=file_id,
                    user_id=user_id,
                    file_url=r2_key,
                    file_name=original_name,
                    file_type="AUDIO"
                )
            except Exception as e:
                logger.error(f"Audio processing failed: {e}")
                import traceback
                traceback.print_exc()
                return self._generate_metadata(file_id, user_id, "", original_name, "AUDIO", status="FAILED")

    def _delete_from_r2(self, object_key: str):
        """
        Deletes a file from R2.
        """
        logger.info(f"Deleting from R2: {object_key}")
        try:
            self.s3_client.delete_object(Bucket=self.r2_bucket, Key=object_key)
        except Exception as e:
            logger.error(f"Failed to delete {object_key} from R2: {e}")

    def process_video_upload(self, file_path: str, user_id: str, original_name: str) -> dict:
        """
        1. Upload Video to R2
        2. Extract Audio -> Azure WAV
        3. Upload WAV to R2
        4. Delete Video from R2
        5. Return Metadata (pointing to Audio)
        """
        file_id = str(uuid.uuid4())
        logger.info(f"Processing Video Upload: {original_name} (ID: {file_id})")

        video_key = f"uploads/{file_id}_video{os.path.splitext(original_name)[1]}"

        try:
            # 1. Upload Video
            self._upload_to_r2(file_path, video_key)
            
            with tempfile.TemporaryDirectory() as temp_dir:
                # 2. Convert/Extract
                wav_filename = f"{file_id}.wav"
                wav_path = os.path.join(temp_dir, wav_filename)
                self._convert_to_azure_wav(file_path, wav_path)

                # 3. Upload Audio
                audio_key = f"uploads/{wav_filename}"
                self._upload_to_r2(wav_path, audio_key)

                # 4. Delete Video
                self._delete_from_r2(video_key)

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
                self._delete_from_r2(video_key)
            except:
                pass
            return self._generate_metadata(file_id, user_id, "", original_name, "VIDEO", status="FAILED")

    def process_document(self, file_path: str, user_id: str, original_name: str, doc_type: str) -> dict:
        """
        Handles PDF, SLIDES (PPTX), MD.
        1. Upload Raw to R2
        2. Return Metadata
        """
        file_id = str(uuid.uuid4())
        logger.info(f"Processing Document ({doc_type}): {original_name} (ID: {file_id})")
        
        try:
            # 1. Upload
            # Preserve extension or just use ID? Using ID to avoid collisions, keeping extension
            ext = os.path.splitext(original_name)[1]
            r2_key = f"documents/{file_id}{ext}"
            self._upload_to_r2(file_path, r2_key)

            return self._generate_metadata(
                file_id=file_id,
                user_id=user_id,
                file_url=r2_key,
                file_name=original_name,
                file_type=doc_type
            )
        except Exception as e:
            logger.error(f"Document processing failed: {e}")
            return self._generate_metadata(file_id, user_id, "", original_name, doc_type, status="FAILED")

if __name__ == "__main__":
    # Test Block
    ingestor = IngestionService()
    
    # 1. Test YouTube
    # print(ingestor.process_youtube("https://www.youtube.com/watch?v=MEUh_y1IFZY", "user_123"))

    # 2. Test Local Audio
    # print(ingestor.process_audio_upload("/Users/vishnu/Downloads/Maroon 5 - One More Night (Lyric Video).mp3", "user_123", "Maroon 5 - One More Night (Lyric Video).mp3"))
    
    # 3. Test Markdown
    # print(ingestor.process_document("/Users/vishnu/Documents/Lumen/lumen/BACKEND_IMPLEMENTATION_PLAN.md", "user_123", "BACKEND_IMPLEMENTATION_PLAN.md", "MD"))

    # 4. Test Video Upload
    # print(ingestor.process_video_upload("/Users/vishnu/Movies/VersatileMageOpening.mp4", "user_123", "VersatileMageOpening.mp4"))

    # 5. Test PPTX
    # print(ingestor.process_document("/Users/vishnu/Documents/Google Takeout/Takeout/Drive/95942_Vishnu_Sai_Aleksandar_Srnec_1419951_12367456.pptx", "user_123", "95942_Vishnu_Sai_Aleksandar_Srnec_1419951_12367456.pptx", "pptx"))
    
    # 6. Test PDF
    # print(ingestor.process_document("/Users/vishnu/Documents/_CSResumesInspo/Shayan_Syed_Resume.pdf", "user_123", "Shayan_Syed_Resume.pdf", "pdf"))
