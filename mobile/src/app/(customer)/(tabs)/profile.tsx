import { Text } from 'react-native-paper';

import { Screen } from '@/components/Screen';
import { ProfileScreen } from '@/features/profile/ProfileScreen';
import { space } from '@/theme';

export default function Profile() {
  return (
    <Screen padTop>
      <Text
        variant="headlineSmall"
        accessibilityRole="header"
        style={{ paddingHorizontal: space.lg, paddingTop: space.lg }}>
        Profile
      </Text>
      <ProfileScreen />
    </Screen>
  );
}
