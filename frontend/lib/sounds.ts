"use client";

import { Howl } from "howler";

// Sound effect mapping
const sounds: Record<string, Howl> = {
  pickup: new Howl({ src: ["/sounds/pickup.mp3"], volume: 0.1 }),
  drop: new Howl({ src: ["/sounds/drop.mp3"], volume: 0.15 }),
  connect: new Howl({ src: ["/sounds/connect.mp3"], volume: 0.2 }),
  delete: new Howl({ src: ["/sounds/delete.mp3"], volume: 0.15 }),
  complete: new Howl({ src: ["/sounds/complete.mp3"], volume: 0.3 }),
  levelup: new Howl({ src: ["/sounds/levelup.mp3"], volume: 0.4 }),
  hover: new Howl({ src: ["/sounds/hover.mp3"], volume: 0.05 }),
  click: new Howl({ src: ["/sounds/click.mp3"], volume: 0.1 }),
};

export function playSound(name: string) {
  if (sounds[name]) {
    try {
      sounds[name].play();
    } catch (e) {
      console.warn("Sound play failed", e);
    }
  }
}
