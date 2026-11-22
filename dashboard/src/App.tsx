import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Layout } from './components/Layout';

// Pages
import { OverviewPage } from './pages/OverviewPage';
import { InboxPage } from './pages/InboxPage';
import { ContentDetailPage } from './pages/ContentDetailPage';
import { HandoffPage } from './pages/HandoffPage';
import { SourcesPage } from './pages/SourcesPage';
import { MonitorPage } from './pages/MonitorPage';
import { SettingsPage } from './pages/SettingsPage';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 5000,
    },
  },
});

export const App: React.FC = () => {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          {/* Dashboard routes with shared Layout (no login: the server only answers this machine) */}
          <Route path="/" element={<Layout />}>
            <Route index element={<OverviewPage />} />
            <Route path="inbox" element={<InboxPage />} />
            <Route path="briefs/:id" element={<ContentDetailPage />} />
            <Route path="handoff" element={<HandoffPage />} />
            <Route path="sources" element={<SourcesPage />} />
            <Route path="monitor" element={<MonitorPage />} />
            <Route path="settings" element={<SettingsPage />} />
          </Route>

          {/* Fallback */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
};

export default App;
