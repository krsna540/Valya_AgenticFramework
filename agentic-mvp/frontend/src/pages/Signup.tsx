import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { ApiError } from "../api/client";

export default function Signup() {
  const { signup } = useAuth();
  const navigate = useNavigate();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [tenantName, setTenantName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await signup(email, fullName, password, tenantName);
      navigate("/app");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Sign up failed");
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
          <h6>New tenant</h6>
          <h1>Stand up your workspace in minutes.</h1>
          <p>
            You'll land as the first admin — invite teammates and connect datasources once you're in. To join an
            existing tenant instead, ask that tenant's admin to add you from Admin &gt; Users.
          </p>
        </div>

        <div className="stats">
          <div>
            <div className="stat-value">1</div>
            <div className="stat-label">Tenant, on you</div>
          </div>
          <div>
            <div className="stat-value">Admin</div>
            <div className="stat-label">Your starting role</div>
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
            <h6>Create account</h6>
            <h2>Get started</h2>
            <p className="sub">Set up a new tenant and your admin login.</p>
          </div>

          <form onSubmit={handleSubmit}>
            <div className="field">
              <label htmlFor="tenantName">Company / tenant name</label>
              <input
                id="tenantName"
                className="input"
                type="text"
                placeholder={fullName ? `${fullName}'s Workspace` : "Acme Corp"}
                value={tenantName}
                onChange={(e) => setTenantName(e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="fullName">Full name</label>
              <input
                id="fullName"
                className="input"
                type="text"
                required
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
              />
            </div>
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
                minLength={8}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
            {error && <p className="error-text">{error}</p>}
            <button className="btn btn-primary btn-block" type="submit" disabled={submitting}>
              {submitting ? "Creating..." : "Create workspace"}
            </button>
          </form>

          <p className="sub" style={{ margin: 0, fontSize: 13 }}>
            Already have a workspace? <Link to="/login">Sign in</Link>
          </p>
        </div>
      </div>
    </div>
  );
}
