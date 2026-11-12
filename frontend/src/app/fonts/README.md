# Bundled fonts

Inter, Lora and JetBrains Mono are bundled for `next/font/local`, so builds do
not fetch CSS or font files from Google. Their existing CSS variables and
variable weight ranges are preserved. These are normal-style variable fonts;
italic styling continues to use browser synthesis as before.

Source: https://github.com/google/fonts/tree/c30b221beb0c1da59d563feb91ec8656a1fa972a/ofl

- `inter/Inter[opsz,wght].ttf`
- `lora/Lora[wght].ttf`
- `jetbrainsmono/JetBrainsMono[wght].ttf`

Each adjacent `*-OFL.txt` contains the upstream SIL Open Font License and
copyright notice. The font files are converted losslessly to WOFF2 with
FontTools; no glyph subsetting or outline modifications are applied.
