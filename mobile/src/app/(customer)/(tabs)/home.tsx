import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { useRouter } from 'expo-router';
import { useEffect, useState } from 'react';
import { FlatList, Pressable, RefreshControl, ScrollView, StyleSheet, View } from 'react-native';
import { Searchbar, Text } from 'react-native-paper';

import type { Product } from '@/api';
import { useProducts, useServiceability } from '@/api/queries';
import { Button } from '@/components/Button';
import { CART_BAR_SPACE, CartBar } from '@/components/CartBar';
import { ProductCard } from '@/components/ProductCard';
import { Screen } from '@/components/Screen';
import { ProductCardSkeleton, Skeleton } from '@/components/Skeleton';
import { EmptyState, ErrorState } from '@/components/StateViews';
import { useSetCartQuantity } from '@/features/cart/useCartActions';
import { categoriesIn, type Category } from '@/features/catalogue/categories';
import { isRescueDeal } from '@/lib/bill';
import { useDebounced } from '@/lib/hooks';
import { useCart } from '@/state/cart';
import { useDeliveryLocation, type DeliveryLocation } from '@/state/deliveryLocation';
import { radius, space, tabularNumbers, TOUCH_TARGET, useAppTheme } from '@/theme';

const GRID_GAP = space.md;
const DEAL_CARD_WIDTH = 156;

export default function Home() {
  const router = useRouter();
  const { colors } = useAppTheme();

  const location = useDeliveryLocation((state) => state.location);
  const setLocation = useDeliveryLocation((state) => state.setLocation);
  const hubId = location?.hubId ?? null;
  const products = useProducts(hubId);
  const point = location ? { lat: location.lat, lng: location.lng } : null;
  const serviceability = useServiceability(point);

  const cartHubId = useCart((state) => state.hubId);
  const cartQuantities = useCart((state) => state.quantities);
  const quantityOf = (productId: number) => (cartHubId === hubId ? (cartQuantities[productId] ?? 0) : 0);
  const setQuantity = useSetCartQuantity();

  const [query, setQuery] = useState('');
  const search = useDebounced(query.trim().toLowerCase(), 150);
  const [categorySlug, setCategorySlug] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  // The remembered address was checked a while ago. If the API now names another hub for it (hubs open, close
  // and get busy), follow the API: the shop must show the stock of the hub that will really deliver.
  const served = serviceability.data?.serviceable ? serviceability.data : null;
  useEffect(() => {
    if (!location || !served) return;
    if (served.hubId !== location.hubId || served.etaMinutes !== location.etaMinutes) {
      setLocation({
        ...location,
        hubId: served.hubId,
        hubName: served.hubName,
        etaMinutes: served.etaMinutes,
        h3Cell: served.h3Cell,
      });
    }
  }, [location, served, setLocation]);

  if (!location) return null; // the tabs layout sends people without an address to the location screen

  const all = products.data ?? [];
  const categories = categoriesIn(all);
  const browsing = search === '' && categorySlug === null;
  const matching = all
    .filter((product) => categorySlug === null || product.category === categorySlug)
    .filter((product) => search === '' || product.name.toLowerCase().includes(search))
    // What can be bought comes first; sold-out items stay visible at the end.
    .sort((a, b) => Number(b.available > 0) - Number(a.available > 0));
  const deals = browsing ? all.filter((product) => isRescueDeal(product) && product.available > 0) : [];
  // An odd number of products would leave the last card stretched across both columns; a blank cell prevents that.
  const cells: (Product | null)[] = matching.length % 2 === 1 ? [...matching, null] : matching;

  const refresh = async () => {
    setRefreshing(true);
    await Promise.all([products.refetch(), serviceability.refetch()]);
    setRefreshing(false);
  };

  const openProduct = (product: Product) => router.push({ pathname: '/product/[id]', params: { id: product.id } });

  const renderCard = (product: Product, cardStyle: object) => (
    <ProductCard
      product={product}
      quantity={quantityOf(product.id)}
      onChangeQuantity={(quantity) => setQuantity(product.id, quantity)}
      onOpen={() => openProduct(product)}
      style={cardStyle}
    />
  );

  const sectionTitle =
    search !== ''
      ? `Results for "${query.trim()}"`
      : (categories.find((category) => category.slug === categorySlug)?.label ?? 'All produce');

  return (
    <Screen padTop>
      <LocationHeader
        location={location}
        etaMinutes={served?.etaMinutes ?? location.etaMinutes}
        onPress={() => router.push('/location')}
      />
      <View style={styles.searchRow}>
        <Searchbar
          value={query}
          onChangeText={setQuery}
          placeholder="Search vegetables, fruits, herbs"
          accessibilityLabel="Search produce"
          elevation={0}
          style={[styles.search, { backgroundColor: colors.surfaceVariant }]}
          inputStyle={styles.searchInput}
        />
      </View>

      {serviceability.data && !serviceability.data.serviceable ? (
        <View style={[styles.notice, { backgroundColor: colors.tertiaryContainer }]} accessibilityRole="alert">
          <Text variant="bodySmall" style={[styles.flex, { color: colors.onTertiaryContainer }]}>
            We are not delivering to this address right now.
          </Text>
          <Button mode="text" compact textColor={colors.onTertiaryContainer} onPress={() => router.push('/location')}>
            Change
          </Button>
        </View>
      ) : null}

      {products.data === undefined && !products.isError ? (
        <HomeSkeleton />
      ) : products.data === undefined ? (
        <ErrorState error={products.error} onRetry={() => products.refetch()} retrying={products.isRefetching} />
      ) : (
        <FlatList
          data={cells}
          keyExtractor={(cell, index) => (cell ? String(cell.id) : `blank-${index}`)}
          numColumns={2}
          columnWrapperStyle={styles.gridRow}
          contentContainerStyle={[styles.grid, { paddingBottom: CART_BAR_SPACE + space.lg }]}
          keyboardShouldPersistTaps="handled"
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={refresh}
              colors={[colors.primary]}
              tintColor={colors.primary}
              progressBackgroundColor={colors.elevation.level2}
            />
          }
          ListHeaderComponent={
            <View>
              <CategoryChips categories={categories} selected={categorySlug} onSelect={setCategorySlug} />
              {deals.length > 0 ? (
                <View style={styles.deals}>
                  <View style={styles.sectionHeader}>
                    <MaterialCommunityIcons name="tag-heart-outline" size={20} color={colors.tertiary} />
                    <View style={styles.flex}>
                      <Text variant="titleMedium">Rescue deals</Text>
                      <Text variant="bodySmall" style={{ color: colors.onSurfaceVariant }}>
                        Last day of freshness, at a lower price
                      </Text>
                    </View>
                  </View>
                  <ScrollView
                    horizontal
                    showsHorizontalScrollIndicator={false}
                    contentContainerStyle={styles.dealStrip}
                    style={styles.bleed}>
                    {deals.map((product) => (
                      <View key={product.id}>{renderCard(product, styles.dealCard)}</View>
                    ))}
                  </ScrollView>
                </View>
              ) : null}
              <Text variant="titleMedium" style={styles.sectionTitle}>
                {sectionTitle}
              </Text>
            </View>
          }
          ListEmptyComponent={
            all.length === 0 ? (
              <EmptyState
                icon="basket-off-outline"
                title="Nothing in stock right now"
                message={`${location.hubName} has no produce listed at the moment. Pull down to check again.`}
              />
            ) : (
              <EmptyState
                icon="shopping-search-outline"
                title="No matches"
                message="Nothing at your hub matches that. Try another name or category.">
                <Button
                  mode="contained-tonal"
                  onPress={() => {
                    setQuery('');
                    setCategorySlug(null);
                  }}>
                  Show all produce
                </Button>
              </EmptyState>
            )
          }
          renderItem={({ item }) => (item ? renderCard(item, styles.gridCard) : <View style={styles.gridCard} />)}
        />
      )}

      <CartBar />
    </Screen>
  );
}

interface LocationHeaderProps {
  location: DeliveryLocation;
  etaMinutes: number;
  onPress: () => void;
}

function LocationHeader({ location, etaMinutes, onPress }: LocationHeaderProps) {
  const { colors } = useAppTheme();
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={`Delivering to ${location.label} from ${location.hubName}, about ${etaMinutes} minutes. Change delivery location`}
      style={({ pressed }) => [styles.header, pressed && styles.pressed]}>
      <View style={[styles.headerPin, { backgroundColor: colors.primaryContainer }]}>
        <MaterialCommunityIcons name="map-marker" size={22} color={colors.onPrimaryContainer} />
      </View>
      <View style={styles.flex}>
        <View style={styles.headerTitle}>
          <Text variant="titleMedium" numberOfLines={1} style={styles.headerLabel}>
            {location.label}
          </Text>
          <MaterialCommunityIcons name="chevron-down" size={20} color={colors.onSurface} />
        </View>
        <Text variant="bodySmall" numberOfLines={1} style={{ color: colors.onSurfaceVariant }}>
          From {location.hubName}
        </Text>
      </View>
      <View style={[styles.eta, { backgroundColor: colors.primary }]}>
        <MaterialCommunityIcons name="clock-outline" size={14} color={colors.onPrimary} />
        <Text variant="labelMedium" style={[tabularNumbers, { color: colors.onPrimary }]}>
          {etaMinutes} min
        </Text>
      </View>
    </Pressable>
  );
}

interface CategoryChipsProps {
  categories: Category[];
  selected: string | null;
  onSelect: (slug: string | null) => void;
}

function CategoryChips({ categories, selected, onSelect }: CategoryChipsProps) {
  const { colors } = useAppTheme();
  const options: { slug: string | null; label: string; icon: Category['icon'] }[] = [
    { slug: null, label: 'All', icon: 'basket-outline' },
    ...categories,
  ];

  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.chips}
      style={styles.bleed}
      accessibilityRole="tablist">
      {options.map((option) => {
        const active = option.slug === selected;
        const ink = active ? colors.onPrimary : colors.onSurface;
        return (
          <Pressable
            key={option.slug ?? 'all'}
            onPress={() => onSelect(option.slug)}
            accessibilityRole="tab"
            accessibilityState={{ selected: active }}
            accessibilityLabel={option.label}
            style={styles.chipTouch}>
            <View
              style={[
                styles.chip,
                active
                  ? { backgroundColor: colors.primary, borderColor: colors.primary }
                  : { backgroundColor: colors.elevation.level1, borderColor: colors.outlineVariant },
              ]}>
              <MaterialCommunityIcons name={option.icon} size={16} color={ink} />
              <Text variant="labelLarge" style={{ color: ink }}>
                {option.label}
              </Text>
            </View>
          </Pressable>
        );
      })}
    </ScrollView>
  );
}

function HomeSkeleton() {
  return (
    <View style={styles.grid} accessibilityLabel="Loading produce">
      <View style={styles.skeletonChips}>
        {[64, 112, 124, 84].map((width) => (
          <Skeleton key={width} width={width} height={36} rounded={radius.pill} />
        ))}
      </View>
      <Skeleton width={140} height={20} style={styles.sectionTitle} />
      {[0, 1].map((row) => (
        <View key={row} style={styles.gridRow}>
          <ProductCardSkeleton />
          <ProductCardSkeleton />
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  pressed: { opacity: 0.7 },
  header: {
    minHeight: 64,
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.md,
    paddingHorizontal: space.lg,
  },
  headerPin: { width: 40, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center' },
  headerTitle: { flexDirection: 'row', alignItems: 'center', gap: 2 },
  headerLabel: { flexShrink: 1 },
  eta: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    borderRadius: radius.pill,
    paddingHorizontal: 10,
    height: 28,
  },
  searchRow: { paddingHorizontal: space.lg, paddingBottom: space.sm },
  search: { height: TOUCH_TARGET, borderRadius: radius.lg },
  searchInput: { minHeight: 0, fontSize: 15 },
  notice: {
    marginHorizontal: space.lg,
    marginBottom: space.sm,
    borderRadius: radius.md,
    paddingLeft: space.md,
    flexDirection: 'row',
    alignItems: 'center',
  },
  grid: { paddingHorizontal: space.lg, gap: GRID_GAP },
  gridRow: { flexDirection: 'row', gap: GRID_GAP },
  // minWidth 0 lets both cards of a row shrink to the same width whatever text they hold.
  gridCard: { flex: 1, minWidth: 0 },
  // Horizontal strips run to the screen edges, past the grid's side padding.
  bleed: { marginHorizontal: -space.lg },
  chips: { paddingHorizontal: space.lg, gap: space.sm },
  chipTouch: { height: TOUCH_TARGET, justifyContent: 'center' },
  chip: {
    height: 36,
    borderRadius: radius.pill,
    borderWidth: 1,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 14,
  },
  skeletonChips: { flexDirection: 'row', gap: space.sm, height: TOUCH_TARGET, alignItems: 'center' },
  deals: { marginTop: space.sm },
  sectionHeader: { flexDirection: 'row', alignItems: 'center', gap: space.sm, marginBottom: space.md },
  dealStrip: { paddingHorizontal: space.lg, gap: GRID_GAP },
  dealCard: { width: DEAL_CARD_WIDTH, flex: 1 },
  sectionTitle: { marginTop: space.lg },
});
