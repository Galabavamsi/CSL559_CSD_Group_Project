import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { Image } from 'expo-image';
import { StyleSheet, View, type StyleProp, type ViewStyle } from 'react-native';

import { categoryOf, productIcon } from '@/features/catalogue/categories';
import { producePhoto } from '@/features/catalogue/photos';
import { radius, useAppTheme } from '@/theme';

import { ProduceGlyph, produceGlyphFor } from './ProduceGlyph';

interface ProductArtProps {
  name: string;
  category?: string;
  imageUrl?: string | null;
  iconSize?: number;
  /** Out of stock: the art is faded. */
  dimmed?: boolean;
  style?: StyleProp<ViewStyle>;
}

/**
 * A product's picture. The batch's own photo (`imageUrl`: from the farmer or the hub's quality check, later) comes
 * first; without one, the catalogue's photograph of that kind of produce; without that, a drawing or an icon on
 * the category's tint, which is also what stays visible while a photo loads.
 */
export function ProductArt({ name, category, imageUrl, iconSize = 56, dimmed = false, style }: ProductArtProps) {
  const { brand } = useAppTheme();
  const tint = brand.tiles[category ? categoryOf(category).tile : 'other'];
  const glyph = produceGlyphFor(name);
  const photo = imageUrl ? { uri: imageUrl } : producePhoto(name);

  return (
    <View style={[styles.tile, { backgroundColor: tint.background }, dimmed && styles.dimmed, style]}>
      {glyph ? (
        <ProduceGlyph name={glyph} size={iconSize} color={tint.foreground} background={tint.background} />
      ) : (
        <MaterialCommunityIcons name={productIcon(name, category)} size={iconSize} color={tint.foreground} />
      )}
      {photo ? (
        <Image
          source={photo}
          style={StyleSheet.absoluteFill}
          contentFit="cover"
          transition={150}
          accessibilityLabel={name}
        />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  tile: {
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: radius.md,
    overflow: 'hidden',
  },
  dimmed: { opacity: 0.45 },
});
