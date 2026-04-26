import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AppLayout } from "@/components/AppLayout";
import Dashboard from "./pages/Dashboard";
import Procurements from "./pages/Procurements";
import RegisterProcurement from "./pages/RegisterProcurement";
import RunDetail from "./pages/RunDetail";
import EvidenceBoard from "./pages/EvidenceBoard";
import Decisions from "./pages/Decisions";
import DecisionDetail from "./pages/DecisionDetail";
import CompanyProfile from "./pages/CompanyProfile";
import Bids from "./pages/Bids";
import BidEditor from "./pages/BidEditor";
import Settings from "./pages/Settings";
import NotFound from "./pages/NotFound.tsx";

const queryClient = new QueryClient();

const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Toaster />
      <Sonner />
      <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Routes>
          <Route element={<AppLayout />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/procurements" element={<Procurements />} />
            <Route path="/procurements/new" element={<RegisterProcurement />} />
            <Route path="/runs/:id" element={<RunDetail />} />
            <Route path="/runs/:id/evidence" element={<EvidenceBoard />} />
            <Route path="/decisions" element={<Decisions />} />
            <Route path="/decisions/:id" element={<DecisionDetail />} />
            <Route path="/bids" element={<Bids />} />
            <Route path="/bids/new" element={<BidEditor />} />
            <Route path="/bids/:bidId/edit" element={<BidEditor />} />
            <Route path="/company" element={<CompanyProfile />} />
            <Route path="/settings" element={<Settings />} />
          </Route>
          {/* ADD ALL CUSTOM ROUTES ABOVE THE CATCH-ALL "*" ROUTE */}
          <Route path="*" element={<NotFound />} />
        </Routes>
      </BrowserRouter>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
