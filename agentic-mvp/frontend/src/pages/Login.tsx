import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { ApiError } from "../api/client";

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email, password);
      navigate("/app");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Login failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-shell">
      <div className="auth-hero">
        <div className="brand">
          <div className="blueprint brand-mark">
            <i className="corner tl" />
            <i className="corner tr" />
            <i className="corner bl" />
            <i className="corner br" />
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <rect x="4" y="4" width="16" height="16" />
              <rect x="9" y="9" width="6" height="6" />
              <path d="M9 2v2M15 2v2M9 20v2M15 20v2M2 9h2M2 15h2M20 9h2M20 15h2" />
            </svg>
          </div>
          <span className="brand-word">KNOWLEDGE NEXUS</span>
        </div>

        <div className="pitch">
          <h6>Knowledge · Expertise · Norms</h6>
          <h1>One nexus for what your organization knows, can do, and must follow.</h1>
          <p>Connect your data, compose reusable playbooks, and enforce guardrails — all from one console, per tenant.</p>
        </div>

        <div className="stats">
          <div>
            <div className="stat-value">3</div>
            <div className="stat-label">Intelligence layers</div>
          </div>
          <div>
            <div className="stat-value">8</div>
            <div className="stat-label">Connector types</div>
          </div>
          <div>
            <div className="stat-value">∞</div>
            <div className="stat-label">Compositions</div>
          </div>
        </div>
      </div>

      <div className="auth-form-col">
        <div className="blueprint card auth-card">
          <i className="corner tl" />
          <i className="corner tr" />
          <i className="corner bl" />
          <i className="corner br" />
          <div>
            <h6>Sign in</h6>
            <h2>Welcome back</h2>
            <p className="sub">Sign in to your Knowledge Nexus workspace.</p>
          </div>

          <form onSubmit={handleSubmit}>
            <div className="field">
              <label htmlFor="email">Email</label>
              <input
                id="email"
                className="input"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="password">Password</label>
              <input
                id="password"
                className="input"
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
            {error && <p className="error-text">{error}</p>}
            <button className="btn btn-primary btn-block" type="submit" disabled={submitting}>
              {submitting ? "Signing in..." : "Sign in"}
            </button>
          </form>

          <p className="sub" style={{ margin: 0, fontSize: 13 }}>
            No account? <Link to="/signup">Create one</Link>
          </p>
          <p className="sub" style={{ margin: 0, fontSize: 12 }}>
            First time setting up the platform? <Link to="/bootstrap-super-admin">Bootstrap Super Admin</Link>
          </p>
        </div>
      </div>
    </div>
  );
}
