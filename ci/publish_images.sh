#!/usr/bin/env bash
# Called only by images.yml after loading and verifying the successful CI artifact.
set -euo pipefail

if [[ "${GITHUB_REPOSITORY:?}" != druidpwnz/antifraud_lab || ! "${IMAGE_TAG:?}" =~ ^[0-9a-f]{40}$ ]]; then
  echo 'Refusing to publish: expected this repository and a full commit SHA.' >&2
  exit 1
fi

# A failed upload leaves :main unchanged. Upload all four commit tags first.
for service in api admin rules generator; do
  docker push "ghcr.io/druidpwnz/antifraud-$service:$IMAGE_TAG"
done

current=$(gh api "repos/$GITHUB_REPOSITORY/git/ref/heads/main" --jq .object.sha)
if [[ "$current" != "$IMAGE_TAG" ]]; then
  echo "A newer commit is on main; keep this SHA's images without moving :main."
  exit 0
fi

# Generator goes last: the future deploy script reads its revision, then pulls
# all four images by that SHA, never a mixture of independently moving :main tags.
for service in api admin rules generator; do
  image="ghcr.io/druidpwnz/antifraud-$service"
  docker tag "$image:$IMAGE_TAG" "$image:main"
  docker push "$image:main"
done
