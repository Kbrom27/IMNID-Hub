import React, { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import { ThemeProvider } from './context/ThemeContext';
import { ConnectionProvider } from './context/ConnectionContext';
import { ToastProvider } from './ui/ToastProvider';
import Layout from './components/Layout';
import { Spinner } from './ui';

// Lazy-loaded route chunks
const Login = lazy(() => import('./pages/Login'));
const Dashboard = lazy(() => import('./pages/Dashboard'));
const Settings = lazy(() => import('./pages/Settings'));
const JobHistory = lazy(() => import('./pages/JobHistory'));
const SmartcarePage = lazy(() => import('./pages/SmartcarePage'));
const DataManagementPage = lazy(() => import('./pages/DataManagementPage'));
const InteropPage = lazy(() => import('./pages/InteropPage'));
const ConceptsPage = lazy(() => import('./pages/ConceptsPage'));
const HmisPage = lazy(() => import('./pages/HmisPage'));

const PageLoader = () => (
  <div className="min-h-[50vh] flex flex-col items-center justify-center p-8 text-slate-400 gap-3">
    <Spinner size="lg" />
    <span className="text-xs font-semibold tracking-wider uppercase text-slate-500">
      Loading view...
    </span>
  </div>
);

const ProtectedRoute = ({ children }) => {
  const { token, loading } = useAuth();
  if (loading) {
    return (
      <div className="h-screen w-screen flex flex-col items-center justify-center bg-slate-950 text-teal-400 gap-3">
        <Spinner size="xl" />
        <span className="text-xs font-mono text-slate-400">Authenticating session...</span>
      </div>
    );
  }
  if (!token) {
    return <Navigate to="/login" replace />;
  }
  return children;
};

import { ErrorBoundary } from './ui';

function App() {
  return (
    <ThemeProvider>
      <ToastProvider>
        <AuthProvider>
          <ConnectionProvider>
            <BrowserRouter>
            <ErrorBoundary>
              <Suspense fallback={<PageLoader />}>
                <Routes>
                <Route path="/login" element={<Login />} />
                <Route
                  path="/"
                  element={
                    <ProtectedRoute>
                      <Layout />
                    </ProtectedRoute>
                  }
                >
                  <Route index element={<Dashboard />} />
                  <Route path="smartcare" element={<SmartcarePage />} />

                  {/* Data Management Hub & Subroutes */}
                  <Route path="data-management" element={<DataManagementPage />} />
                  <Route path="data-management/:feature" element={<DataManagementPage />} />

                  {/* Interoperability Pipelines & Subroutes */}
                  <Route path="interop" element={<InteropPage />} />
                  <Route path="interop/:feature" element={<InteropPage />} />

                  {/* Concepts & Forms & Subroutes */}
                  <Route path="concepts" element={<ConceptsPage />} />
                  <Route path="concepts/:feature" element={<ConceptsPage />} />

                  {/* HMIS Reporting & Subroutes */}
                  <Route path="hmis" element={<HmisPage />} />
                  <Route path="hmis/:feature" element={<HmisPage />} />

                  <Route path="jobs" element={<JobHistory />} />
                  <Route path="settings" element={<Settings />} />
                </Route>
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </Suspense>
          </ErrorBoundary>
        </BrowserRouter>
      </ConnectionProvider>
    </AuthProvider>
    </ToastProvider>
  </ThemeProvider>
);
}

export default App;
