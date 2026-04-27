import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AppLayout } from "@/components/AppLayout";
import { AuthProvider, RequireAuth } from "@/lib/auth";
import Dashboard from "./pages/Dashboard";
import Procurements from "./pages/Procurements";
import RegisterProcurement from "./pages/RegisterProcurement";
import RunDetail from "./pages/RunDetail";
import EvidenceBoard from "./pages/EvidenceBoard";
import DecisionDetail from "./pages/DecisionDetail";
import CompanyProfile from "./pages/CompanyProfile";
import Bids from "./pages/Bids";
import BidEditor from "./pages/BidEditor";
import BidDraft from "./pages/BidDraft";
import Settings from "./pages/Settings";
import Login from "./pages/Login";
import NotFound from "./pages/NotFound.tsx";
import ExploreProcurements from "./pages/ExploreProcurements";
import ExploreTenderDetail from "./pages/ExploreTenderDetail";

const queryClient = new QueryClient();

const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Toaster />
      <Sonner />
      <AuthProvider>
        <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route
              element={
                <RequireAuth>
                  <AppLayout />
                </RequireAuth>
              }
            >
              <Route path="/" element={<Dashboard />} />
              <Route path="/procurements" element={<Procurements />} />
              <Route path="/procurements/explore" element={<ExploreProcurements />} />
              <Route path="/procurements/explore/:id" element={<ExploreTenderDetail />} />
              <Route path="/procurements/new" element={<RegisterProcurement />} />
              <Route path="/runs/:id" element={<RunDetail />} />
              <Route path="/runs/:id/evidence" element={<EvidenceBoard />} />
              <Route path="/decisions/:id" element={<DecisionDetail />} />
              <Route path="/bids" element={<Bids />} />
              <Route path="/bids/new" element={<BidEditor />} />
              <Route path="/bids/:bidId/edit" element={<BidEditor />} />
              <Route path="/drafts/:runId" element={<BidDraft />} />
              <Route path="/company" element={<CompanyProfile />} />
              <Route path="/settings" element={<Settings />} />
            </Route>
            {/* ADD ALL CUSTOM ROUTES ABOVE THE CATCH-ALL "*" ROUTE */}
            <Route path="*" element={<NotFound />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
