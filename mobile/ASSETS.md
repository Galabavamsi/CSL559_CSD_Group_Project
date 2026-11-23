# Assets and their licences

Everything that shapes how the app looks, where it comes from, and the licence it is under. Nothing here is taken
from another shopping app: no logos, artwork, names or screen designs. Versions are the ones in `package.json`.

## Made for this project

| Asset | Where | Notes |
| --- | --- | --- |
| Logo mark (map pin, house, leaf) | `src/components/brand/logo-paths.json`, drawn by `src/components/brand/Logo.tsx` | Original. Four hand-written SVG paths. |
| Wordmark "Farm2Home" | `src/components/brand/Wordmark.tsx` | Original. Plain text set in Plus Jakarta Sans ExtraBold (see below). |
| App icon, Android adaptive icon layers, splash image, favicon | `assets/images/*.png` | Original. Generated from the logo paths by `scripts/make-icons.mjs` (`npm run icons`). |
| Colour theme (light and dark) | `src/theme/colors.ts` | Original values, arranged in Material Design 3's colour roles. |
| Product art tiles | `src/components/ProductArt.tsx` | A tinted tile with an icon from the icon set below. No photographs are shipped; a product's own `image_url` is shown when the API sends one. |
| Produce drawings (onion, potato, brinjal, cauliflower, okra, banana) | `src/components/ProduceGlyph.tsx` | Original. Small hand-written SVG drawings for produce the icon set has no symbol for. |
| Demo catalogue, farm names, hub names | `src/api/mock/data.ts` | Invented for the demo. The farm and people names are made up. |

## Third-party

| Asset or library | Used for | Licence | Source |
| --- | --- | --- | --- |
| Plus Jakarta Sans (weights 400, 500, 600, 700, 800) | The app's only typeface | SIL Open Font License 1.1. Copyright 2020 The Plus Jakarta Sans Project Authors | `@expo-google-fonts/plus-jakarta-sans` 0.4.2 (package code MIT) |
| Material Design Icons (the "MaterialCommunityIcons" set) | Every icon in the app, including the icons on product tiles | Apache License 2.0 (the Pictogrammers Free License) | Bundled as a font in `@expo/vector-icons` 15 (package code MIT) |
| react-native-paper 5.15 | Material Design 3 components: buttons, text fields, dialogs, app bar, snackbar | MIT (Callstack) | npm |
| react-native-svg 15.16 | Drawing the logo | MIT | npm |
| expo-image 58 | Showing a product photo when the API provides one | MIT | npm |
| Expo SDK 58, Expo Router, React Native 0.88, React 19 | The app framework | MIT | npm |
| Project scaffold | `tsconfig.json`, `.gitignore`, `.vscode/` started from `create-expo-app`'s default template; its sample screens and images were removed | MIT (650 Industries) | `npx create-expo-app@latest` |

Material Design 3 itself (the layout and component guidelines by Google) is followed as a design system; no Google
artwork is included.

## Not present, on purpose

- No stock photos, and no photos of produce at all. Real photos will come from farmers' uploads.
- No map tiles or maps SDK yet. The location screen uses the phone's GPS and a list of areas.
- No logos, names, artwork or screens of Blinkit, Swiggy Instamart, Ninjacart or any other company. Those apps
  were looked at only for general layout ideas of the genre: a location header, category chips, a deals strip, a
  two-column product grid and a floating cart bar.
