import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { ApiError } from "../api/client";

// One-time-only page: POST /auth/bootstrap-super-admin self-disables (404s)
// the moment a super_admin row exists anywhere in the system, so this page
// only does anything useful on a completely fresh install. See
// docs/AUTHORIZATION.md.
export default function BootstrapSuperAdmin() {
  const { bootstrapSuperAdmin } = useAuth();
  const navigate = useNavigate();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [alreadyBootstrapped, setAlreadyBootstrapped] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setAlreadyBootstrapped(false);
    setSubmitting(true);
    try {
      await bootstrapSuperAdmin(email, fullName, password);
      navigate("/app/platform/tenants");
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setAlreadyBootstrapped(true);
      } else {
        setError(err instanceof ApiError ? err.message : "Bootstrap failed");
      }
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
          <h6>Platform setup</h6>
          <h1>Create the first Super Admin.</h1>
          <p>
            This runs once, on a fresh install only. The Super Admin creates tenants and assigns each one its first
            Admin — everyday tenant work (users, projects, skills, agents) happens inside those tenants, not here.
          </p>
        </div>
      </div>

      <div className="auth-form-col">
        <div className="blueprint card auth-card">
          <i className="corner tl" />
          <i className="corner tr" />
          <i className="corner bl" />
          <i className="corner br" />
          <div>
            <h6>Bootstrap</h6>
            <h2>Super Admin account</h2>
            <p className="sub">Only works if no Super Admin exists yet.</p>
          </div>

          {alreadyBootstrapped ? (
            <div>
              <p className="error-text">
                A Super Admin already exists — this setup step has already been completed.
              </p>
              <p className="sub" style={{ margin: 0, fontSize: 13 }}>
                <Link to="/login">Go to sign in</Link>
              </p>
            </div>
          ) : (
            <form onSubmit={handleSubmit}>
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
                {submitting ? "Creating..." : "Create Super Admin"}
              </button>
            </form>
          )}

          <p className="sub" style={{ margin: 0, fontSize: 13 }}>
            Already set up? <Link to="/login">Sign in</Link>
          </p>
        </div>
      </div>
    </div>
  );
}
