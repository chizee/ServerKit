import { useEffect } from 'react';
import { Routes, Route, Navigate, useLocation, useNavigate } from 'react-router-dom';
import Shell from './components/Shell.jsx';
import Overview from './pages/Overview.jsx';
import Activity from './pages/Activity.jsx';
import Logs from './pages/Logs.jsx';
import Actions from './pages/Actions.jsx';
import About from './pages/About.jsx';
import Pair from './pages/Pair.jsx';
import { useStatus } from './ipc/hooks.js';

// PairGate redirects to /pair when the agent isn't registered yet, except
// from /pair itself (so the wizard can render its "claimed" stage). Once
// the agent is paired and we're on /pair, send the user to /overview.
function PairGate({ children }) {
    const { status } = useStatus(2000);
    const location = useLocation();
    const navigate = useNavigate();

    useEffect(() => {
        if (!status) return;
        const onPair = location.pathname === '/pair';
        if (!status.registered && !onPair) {
            navigate('/pair', { replace: true });
        }
    }, [status, location.pathname, navigate]);

    return children;
}

export default function App() {
    return (
        <PairGate>
            <Routes>
                <Route path="/pair" element={<Pair />} />
                <Route element={<Shell />}>
                    <Route path="/overview" element={<Overview />} />
                    <Route path="/activity" element={<Activity />} />
                    <Route path="/logs" element={<Logs />} />
                    <Route path="/actions" element={<Actions />} />
                    <Route path="/about" element={<About />} />
                </Route>
                <Route path="*" element={<Navigate to="/overview" replace />} />
            </Routes>
        </PairGate>
    );
}
