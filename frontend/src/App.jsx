import { BrowserRouter, Routes, Route, NavLink } from "react-router-dom";
import Accounts from "./pages/Accounts";
import Campaigns from "./pages/Campaigns";
import Conversations from "./pages/Conversations";
import Settings from "./pages/Settings";
import { useWS } from "./ws";

function Nav() {
  const linkClass = ({ isActive }) =>
    `px-4 py-2 rounded text-sm font-medium transition-colors ${
      isActive ? "bg-blue-600 text-white" : "text-gray-300 hover:text-white hover:bg-gray-700"
    }`;
  return (
    <nav className="bg-gray-900 border-b border-gray-700 px-6 py-3 flex items-center gap-2">
      <span className="text-white font-bold text-lg mr-6">TG Outreach</span>
      <NavLink to="/" end className={linkClass}>Conversations</NavLink>
      <NavLink to="/accounts" className={linkClass}>Accounts</NavLink>
      <NavLink to="/campaigns" className={linkClass}>Campaigns</NavLink>
      <NavLink to="/settings" className={linkClass}>Settings</NavLink>
    </nav>
  );
}

export default function App() {
  useWS(); // global WS connection
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-gray-950 text-gray-100 flex flex-col">
        <Nav />
        <div className="flex-1 overflow-auto">
          <Routes>
            <Route path="/" element={<Conversations />} />
            <Route path="/accounts" element={<Accounts />} />
            <Route path="/campaigns" element={<Campaigns />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </div>
      </div>
    </BrowserRouter>
  );
}
