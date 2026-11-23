import { Screen } from '@/components/Screen';
import { TopBar } from '@/components/TopBar';
import { ProfileScreen } from '@/features/profile/ProfileScreen';

/** The profile screen for farmers and delivery agents, who reach it from the account button on their home. */
export default function Account() {
  return (
    <Screen>
      <TopBar title="Account" />
      <ProfileScreen />
    </Screen>
  );
}
