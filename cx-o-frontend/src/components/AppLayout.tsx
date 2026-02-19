import { Outlet } from 'react-router-dom';
import { Layout, Sidebar, Header } from './layout';

export function AppLayout() {
  return (
    <Layout sidebar={(props) => <Sidebar {...props} />} header={<Header />}>
      <main className="p-6">
        <Outlet />
      </main>
    </Layout>
  );
}
