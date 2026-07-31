import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import {render} from '@testing-library/react';
import type {ReactElement} from 'react';
import {MemoryRouter} from 'react-router-dom';

import {ToastProvider} from '@/components/Toast';

export function renderWithApp(ui: ReactElement, initialEntries: string[] = ['/stories']) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {retry: false},
      mutations: {retry: false},
    },
  });
  const wrap = (element: ReactElement) => (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={initialEntries}>
        <ToastProvider>{element}</ToastProvider>
      </MemoryRouter>
    </QueryClientProvider>
  );
  const result = render(wrap(ui));
  return {
    queryClient,
    ...result,
    rerender: (nextUi: ReactElement) => result.rerender(wrap(nextUi)),
  };
}
