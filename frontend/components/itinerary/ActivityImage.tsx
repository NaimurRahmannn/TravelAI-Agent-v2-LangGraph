"use client";

import Image from "next/image";
import { ImageOff } from "lucide-react";
import { useState } from "react";
import type { PlaceImage } from "@/lib/api";
import {
  isSafeExternalUrl,
  trustedWikimediaImageUrl,
} from "./formatters";

type ActivityImageProps = {
  activityName: string;
  image: PlaceImage;
};

export function ActivityImage({ activityName, image }: ActivityImageProps) {
  const [failed, setFailed] = useState(false);
  const imageUrl = trustedWikimediaImageUrl(
    image.thumbnail_url,
    image.original_url,
  );

  if (image.provider !== "wikimedia_commons" || !imageUrl) {
    return null;
  }

  if (failed) {
    return (
      <div className="activityImageFallback" role="status">
        <ImageOff aria-hidden="true" size={22} />
        <span>Photo unavailable</span>
      </div>
    );
  }

  const creator = image.author?.trim() || image.credit?.trim() || null;
  const licenseUrl = isSafeExternalUrl(image.license_url)
    ? image.license_url
    : null;
  const sourceUrl = isSafeExternalUrl(image.source_page_url)
    ? image.source_page_url
    : null;

  return (
    <figure className="activityImage">
      <div className="activityImageFrame">
        <Image
          alt={`Photo of ${activityName}`}
          fill
          loading="lazy"
          onError={() => setFailed(true)}
          sizes="(max-width: 720px) 100vw, (max-width: 1200px) 55vw, 420px"
          src={imageUrl}
        />
      </div>
      <figcaption className="imageAttribution">
        {creator ? (
          <>
            <span>Photo: {creator}</span>
            <span aria-hidden="true">/</span>
            {licenseUrl ? (
              <a href={licenseUrl} rel="noopener noreferrer" target="_blank">
                {image.license_short_name}
              </a>
            ) : (
              <span>{image.license_short_name}</span>
            )}
            <span aria-hidden="true">/</span>
            {sourceUrl ? (
              <a href={sourceUrl} rel="noopener noreferrer" target="_blank">
                Wikimedia Commons
              </a>
            ) : (
              <span>Wikimedia Commons</span>
            )}
          </>
        ) : (
          <>
            <span>{image.attribution_text}</span>
            {licenseUrl ? (
              <>
                <span aria-hidden="true">/</span>
                <a href={licenseUrl} rel="noopener noreferrer" target="_blank">
                  License terms
                </a>
              </>
            ) : null}
            {sourceUrl ? (
              <>
                <span aria-hidden="true">/</span>
                <a href={sourceUrl} rel="noopener noreferrer" target="_blank">
                  Commons source
                </a>
              </>
            ) : null}
          </>
        )}
      </figcaption>
    </figure>
  );
}
