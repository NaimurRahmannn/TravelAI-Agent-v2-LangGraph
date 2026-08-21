"use client";

import Image from "next/image";
import { ImageOff } from "lucide-react";
import { useState } from "react";
import type { PlaceImage } from "@/lib/api";
import {
  isSafeExternalUrl,
  trustedPlaceImageUrl,
} from "./formatters";

type ActivityImageProps = {
  activityName: string;
  image: PlaceImage;
};

export function ActivityImage({ activityName, image }: ActivityImageProps) {
  const [failed, setFailed] = useState(false);
  const imageUrl = trustedPlaceImageUrl(
    image.provider,
    image.thumbnail_url,
    image.original_url,
  );

  if (!imageUrl) {
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
  const creatorUrl = isSafeExternalUrl(image.author_url)
    ? image.author_url
    : null;
  const licenseUrl = isSafeExternalUrl(image.license_url)
    ? image.license_url
    : null;
  const sourceUrl = isSafeExternalUrl(image.source_page_url)
    ? image.source_page_url
    : null;
  const sourceName =
    image.provider === "pexels" ? "Pexels" : "Wikimedia Commons";

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
            {creatorUrl ? (
              <a href={creatorUrl} rel="noopener noreferrer" target="_blank">
                Photo: {creator}
              </a>
            ) : (
              <span>Photo: {creator}</span>
            )}
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
                {sourceName}
              </a>
            ) : (
              <span>{sourceName}</span>
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
                  {sourceName} source
                </a>
              </>
            ) : null}
          </>
        )}
      </figcaption>
    </figure>
  );
}
