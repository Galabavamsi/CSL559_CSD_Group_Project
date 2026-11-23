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
| Product art tiles | `src/components/ProductArt.tsx` | A product's own `image_url` when the API sends one; otherwise the catalogue photograph of that produce (below); otherwise a tinted tile with a drawing or an icon. |
| Produce drawings (onion, potato, brinjal, cauliflower, okra, banana) | `src/components/ProduceGlyph.tsx` | Original. Small hand-written SVG drawings for produce the icon set has no symbol for. |
| Demo catalogue, farm names, hub names | `src/api/mock/data.ts` | Invented for the demo. The farm and people names are made up. |

## Photographs of produce

One photograph for each kind of produce in the catalogue, from Wikimedia Commons, resized by Commons to 500 px
wide and otherwise unchanged. They were found with the Firecrawl CLI through Commons' search, limited to
openly licensed files, and chosen by eye. Public domain and CC0 files carry no conditions. The CC BY files
must be credited to their authors: this table is that credit, and the app's product pages should show it too
before a public release.

| Photo | Shows | Author | Licence | Source |
| --- | --- | --- | --- | --- |
| `assets/produce/tomato.jpg` | Tomato | Jeffery Martin | [CC0](http://creativecommons.org/publicdomain/zero/1.0/deed.en) | [Commons](https://commons.wikimedia.org/wiki/File:Tomatoes_for_sale.jpg) |
| `assets/produce/onion.jpg` | Onion | Natashadonoh | [CC0](http://creativecommons.org/publicdomain/zero/1.0/deed.en) | [Commons](https://commons.wikimedia.org/wiki/File:Bowl_of_onions_18th_march_2025.jpg) |
| `assets/produce/potato.jpg` | Potato | Scott Bauer, USDA ARS | Public domain | [Commons](https://commons.wikimedia.org/wiki/File:Patates.jpg) |
| `assets/produce/carrot.jpg` | Carrot | Mink Mingle minkmingle | [CC0](http://creativecommons.org/publicdomain/zero/1.0/deed.en) | [Commons](https://commons.wikimedia.org/wiki/File:Carrots_(Unsplash).jpg) |
| `assets/produce/cauliflower.jpg` | Cauliflower | Jeffery Martin | [CC0](http://creativecommons.org/publicdomain/zero/1.0/deed.en) | [Commons](https://commons.wikimedia.org/wiki/File:Cauliflower_heads_on_a_shelf.jpg) |
| `assets/produce/okra.jpg` | Okra | Paul Lowry | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0) | [Commons](https://commons.wikimedia.org/wiki/File:Okra_in_Baton_Rouge,_Louisiana.jpg) |
| `assets/produce/brinjal.jpg` | Brinjal | Leon Brooks | Public domain | [Commons](https://commons.wikimedia.org/wiki/File:Eggplant_vegetable_aubergines.jpg) |
| `assets/produce/green-chilli.jpg` | Green chilli | U.S. Air Force photo by Tech. Sgt. Michael B. Keller | Public domain | [Commons](https://commons.wikimedia.org/wiki/File:Peppers_for_sale.JPG) |
| `assets/produce/spinach.jpg` | Spinach | Judgefloro | [CC0](http://creativecommons.org/publicdomain/zero/1.0/deed.en) | [Commons](https://commons.wikimedia.org/wiki/File:774Spinach_leaves_05.jpg) |
| `assets/produce/coriander.jpg` | Coriander | Alabama Extension | [CC0](http://creativecommons.org/publicdomain/zero/1.0/deed.en) | [Commons](https://commons.wikimedia.org/wiki/File:Cilantro_(Alabama_Extension).jpg) |
| `assets/produce/banana.jpg` | Banana | Wilfredor | [CC0](http://creativecommons.org/publicdomain/zero/1.0/deed.en) | [Commons](https://commons.wikimedia.org/wiki/File:Bunch_of_bananas_on_sale.jpg) |
| `assets/produce/guava.jpg` | Guava | Sarang | Public domain | [Commons](https://commons.wikimedia.org/wiki/File:Guava_-_Psidium_guajava_fruit_of_Cuba.jpg) |
| `assets/produce/bottle-gourd.jpg` | Bottle gourd | Hyunjung Kim | [CC0](http://creativecommons.org/publicdomain/zero/1.0/deed.en) | [Commons](https://commons.wikimedia.org/wiki/File:Calabash_(Lagenaria_siceraria)_in_Seoul_3.jpg) |
| `assets/produce/cabbage.jpg` | Cabbage | George Chernilevsky | Public domain | [Commons](https://commons.wikimedia.org/wiki/File:Brassica_oleracea_2011_G1.jpg) |
| `assets/produce/curry-leaves.jpg` | Curry leaves | Harsha099 | [CC0](http://creativecommons.org/publicdomain/zero/1.0/deed.en) | [Commons](https://commons.wikimedia.org/wiki/File:Curry_leaves_of_the_tree.jpg) |
| `assets/produce/fenugreek-leaves.jpg` | Fenugreek leaves | Miansari66 | Public domain | [Commons](https://commons.wikimedia.org/wiki/File:Qasuri_Methi.JPG) |
| `assets/produce/ginger.jpg` | Ginger | Rubel Das | [CC0](http://creativecommons.org/publicdomain/zero/1.0/deed.en) | [Commons](https://commons.wikimedia.org/wiki/File:Ginger_Root_(Zingiber_officinale).jpg) |
| `assets/produce/lemon.jpg` | Lemon | ASADAL, Inc. | [CC BY 2.0 kr](https://creativecommons.org/licenses/by/2.0/kr/deed.en) | [Commons](https://commons.wikimedia.org/wiki/File:Lemons_3.jpg) |
| `assets/produce/mint.jpg` | Mint | Aviavlad | [CC0](http://creativecommons.org/publicdomain/zero/1.0/deed.en) | [Commons](https://commons.wikimedia.org/wiki/File:Mint_leaves_raster.jpg) |
| `assets/produce/papaya.jpg` | Papaya | Judgefloro | [CC0](http://creativecommons.org/publicdomain/zero/1.0/deed.en) | [Commons](https://commons.wikimedia.org/wiki/File:330Carica_papaya_seeds_01.jpg) |
| `assets/produce/pomegranate.jpg` | Pomegranate | Fumikas Sagisavas | [CC0](http://creativecommons.org/publicdomain/zero/1.0/deed.en) | [Commons](https://commons.wikimedia.org/wiki/File:Soft_seed_pomegranate.jpg) |
| `assets/produce/red-amaranth.jpg` | Red amaranth | Matthieu Bonneau | [CC0](http://creativecommons.org/publicdomain/zero/1.0/deed.en) | [Commons](https://commons.wikimedia.org/wiki/File:Amaranthe_(153366305).jpeg) |
| `assets/produce/spring-onion.jpg` | Spring onion | Evan-Amos | Public domain | [Commons](https://commons.wikimedia.org/wiki/File:CSA-Red-Spring-Onions.jpg) |
| `assets/produce/sweet-corn.jpg` | Sweet corn | Nutrition, Food Safety & Health | [CC0](http://creativecommons.org/publicdomain/zero/1.0/deed.en) | [Commons](https://commons.wikimedia.org/wiki/File:Corn_on_the_cob_(sweet_corn).jpg) |
| `assets/produce/watermelon.jpg` | Watermelon | liz west from Boxborough, MA, USA | [CC BY 2.0](https://creativecommons.org/licenses/by/2.0) | [Commons](https://commons.wikimedia.org/wiki/File:Cut_watermelon_squared_circle_-_Flickr_-_Muffet.jpg) |

## Photographs of packaged goods

One photograph for each of the packaged items some hubs stock, from Wikimedia Commons in the same way as the
produce photographs above: openly licensed, resized by Commons to 500 px wide and chosen by eye.

| Photo | Shows | Author | Licence | Source |
| --- | --- | --- | --- | --- |
| `assets/produce/milk.jpg` | Milk | Daria-Yakovleva | [CC0](http://creativecommons.org/publicdomain/zero/1.0/deed.en) | [Commons](https://commons.wikimedia.org/wiki/File:Milk_2.jpg) |
| `assets/produce/curd.jpg` | Curd | Julikalucky | [CC0](http://creativecommons.org/publicdomain/zero/1.0/deed.en) | [Commons](https://commons.wikimedia.org/wiki/File:Yoghurt_and_spoon.jpg) |
| `assets/produce/paneer.jpg` | Paneer | Ian Brown | [CC BY 2.0](https://creativecommons.org/licenses/by/2.0) | [Commons](https://commons.wikimedia.org/wiki/File:Homemade_Paneer_cut_into_pieces_for_cooking_Cheese_Fromage_India.jpg) |
| `assets/produce/bread.jpg` | Bread | Evan Swigart from Chicago, USA | [CC BY 2.0](https://creativecommons.org/licenses/by/2.0) | [Commons](https://commons.wikimedia.org/wiki/File:Homemade_White_Bread_with_Strawberry_Jam.jpg) |
| `assets/produce/eggs.jpg` | Eggs | safaritravelplus | [CC0](http://creativecommons.org/publicdomain/zero/1.0/deed.en) | [Commons](https://commons.wikimedia.org/wiki/File:A_Tray_Of_Eggs.jpg) |
| `assets/produce/rice.jpg` | Rice | cookbookman17 | [CC BY 2.0](https://creativecommons.org/licenses/by/2.0) | [Commons](https://commons.wikimedia.org/wiki/File:Basmati_Rice_India,_raw.jpg) |
| `assets/produce/atta.jpg` | Atta (wheat flour) | Margaret Hoogstrate | [CC BY 3.0](https://creativecommons.org/licenses/by/3.0) | [Commons](https://commons.wikimedia.org/wiki/File:Whole_wheat_grain_flour_being_scooped.jpg) |
| `assets/produce/sugar.jpg` | Sugar | Douglas P Perkins | [CC BY 3.0](https://creativecommons.org/licenses/by/3.0) | [Commons](https://commons.wikimedia.org/wiki/File:Bowl_of_white_sugar_without_background.jpg) |
| `assets/produce/tea.jpg` | Tea | HeroidShehu | [CC BY 3.0](https://creativecommons.org/licenses/by/3.0) | [Commons](https://commons.wikimedia.org/wiki/File:Ceylon_tea_Leafs.JPG) |
| `assets/produce/noodles.jpg` | Instant noodles | Ninosan | [CC0](http://creativecommons.org/publicdomain/zero/1.0/deed.en) | [Commons](https://commons.wikimedia.org/wiki/File:Typical_instant_noodles.jpg) |
| `assets/produce/chips.jpg` | Potato chips | Evan-Amos | Public domain | [Commons](https://commons.wikimedia.org/wiki/File:Potato-Chips.jpg) |
| `assets/produce/oil.jpg` | Cooking oil | margenauer from Pixabay | [CC0](http://creativecommons.org/publicdomain/zero/1.0/deed.en) | [Commons](https://commons.wikimedia.org/wiki/File:Bottle_of_olive_oil.jpg) |
| `assets/produce/ice-cream.jpg` | Ice cream | Benreis | [CC BY 3.0](https://creativecommons.org/licenses/by/3.0) | [Commons](https://commons.wikimedia.org/wiki/File:Vanilleeis_Rote_Gr%C3%BCtze_Flensburg.JPG) |
| `assets/produce/green-peas.jpg` | Green peas | Paul Wilkinson from London, United Kingdom | [CC BY 2.0](https://creativecommons.org/licenses/by/2.0) | [Commons](https://commons.wikimedia.org/wiki/File:Frozen_Peas_(8042519481).jpg) |
| `assets/produce/soap.jpg` | Soap | TheLewisRepublic | Public domain | [Commons](https://commons.wikimedia.org/wiki/File:Soap_in_blue_dish.JPG) |

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

- No photos taken from another shop's catalogue. The catalogue photographs above are openly licensed; a batch's
  own photo from the farmer or the hub will replace them when the API sends one.
- No map tiles or maps SDK yet. The location screen uses the phone's GPS and a list of areas.
- No logos, names, artwork or screens of Blinkit, Swiggy Instamart, Ninjacart or any other company. Those apps
  were looked at only for general layout ideas of the genre: a location header, category chips, a deals strip, a
  two-column product grid and a floating cart bar.
