# k6 for the load harness (IFORA-59). Pinned by digest like every other image (make image-pins).
# Refresh: docker buildx imagetools inspect grafana/k6:<version>   (use the top-level "Digest:")
FROM grafana/k6:1.4.2@sha256:3656673de3f30424e8ebcfa46acd9558d83b6a43612d0f668ffeac953950c6c7
