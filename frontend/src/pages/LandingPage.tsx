import { Link, Navigate } from "react-router-dom";

import { useAuth } from "../auth/AuthProvider";

const steps = [
  { number: "01", title: "Describe the fit", copy: "Write what you need in your own words. Add audience, industry, size, or budget requirements when they matter." },
  { number: "02", title: "Review the shortlist", copy: "Spark finds relevant creators or companies, ranks the candidates, and shows the reasons behind each match." },
  { number: "03", title: "Move forward", copy: "Compare candidates, revisit past searches, and export the shortlist for your next step." },
];

export function LandingPage() {
  const { session, loading } = useAuth();
  if (loading) {
    return <main className="landing-auth-loading" aria-busy="true"><img src="/logo-mark.png" alt="" /><span>Opening Spark…</span></main>;
  }
  if (session) return <Navigate to="/creators/search" replace />;

  return (
    <main className="landing-page">
      <div className="landing-ambient landing-ambient-one" aria-hidden="true" />
      <div className="landing-ambient landing-ambient-two" aria-hidden="true" />
      <header className="landing-nav-wrap">
        <nav className="landing-nav" aria-label="Main navigation">
          <a className="landing-brand" href="#top" aria-label="Spark home">
            <img src="/logo-mark.png" alt="" width={34} height={34} />
            <span>Spark</span>
          </a>
          <div className="landing-nav-links">
            <a href="#product">Product</a>
            <a href="#how-it-works">How it works</a>
          </div>
          <div className="landing-nav-actions">
            <Link className="landing-signin" to="/login">Sign in</Link>
            <Link className="landing-button landing-button-small" to="/signup">Get started <span aria-hidden="true">↗</span></Link>
          </div>
        </nav>
      </header>

      <section className="landing-hero" id="top" aria-labelledby="landing-title">
        <div className="landing-hero-copy">
          <div className="landing-kicker"><span className="landing-kicker-dot" /> CREATOR DISCOVERY · COMPANY PROSPECTING</div>
          <h1 id="landing-title">From a rough brief to your <span>next best match.</span></h1>
          <p className="landing-hero-description">
            Find creators who fit your campaign and early-stage companies that fit your ICP. Spark turns plain-language briefs into ranked, explainable shortlists.
          </p>
          <div className="landing-hero-actions">
            <Link className="landing-button" to="/signup">Create your workspace <span aria-hidden="true">→</span></Link>
            <a className="landing-text-link" href="#product">Explore the product <span aria-hidden="true">↓</span></a>
          </div>
          <div className="landing-assurance">
            <span className="landing-assurance-icon" aria-hidden="true">✳</span>
            <span>Built for decisions you can explain.</span>
          </div>
        </div>

        <div className="landing-hero-visual" role="img" aria-label="Sample preview of Spark's creator matching workspace">
          <div className="landing-preview-glow" aria-hidden="true" />
          <ProductPreview />
          <div className="landing-float-note">
            <span className="landing-float-check" aria-hidden="true">✓</span>
            <span><strong>Why it fits</strong><small>Evidence alongside every match</small></span>
          </div>
          <div className="landing-preview-caption"><span className="caption-pulse" /> PRODUCT PREVIEW <span>·</span> SAMPLE DATA</div>
        </div>
      </section>

      <section className="landing-proofline" aria-label="Spark capabilities">
        <span>One clear workflow</span><i />
        <span>Two purpose-built search panels</span><i />
        <span>Every shortlist stays within reach</span>
      </section>

      <section className="landing-product section-container" id="product" aria-labelledby="product-title">
        <div className="landing-section-heading">
          <p className="landing-overline">A better way to find your fit</p>
          <h2 id="product-title">Good matches start with<br /><span>the whole picture.</span></h2>
          <p>Move past one-size-fits-all filters. Search the context around a match, then see what makes each candidate worth a closer look.</p>
        </div>

        <div className="landing-feature-grid">
          <article className="landing-feature-card creator-feature">
            <div className="landing-feature-topline"><span className="feature-index">01</span><span className="feature-label">CREATOR MATCHING</span></div>
            <h3>Find creators who feel right for your brand.</h3>
            <p>Match on content, audience, reach, and campaign intent—not follower count alone.</p>
            <CreatorVisual />
            <Link to="/signup" className="landing-card-link">Explore creator matching <span aria-hidden="true">↗</span></Link>
          </article>

          <article className="landing-feature-card company-feature">
            <div className="landing-feature-topline"><span className="feature-index">02</span><span className="feature-label">COMPANY MATCHING</span></div>
            <h3>Find emerging companies that fit your ICP.</h3>
            <p>Surface companies by what they do, their stage, their size, and the needs they signal.</p>
            <CompanyVisual />
            <Link to="/signup" className="landing-card-link">Explore company matching <span aria-hidden="true">↗</span></Link>
          </article>
        </div>
      </section>

      <section className="landing-process" id="how-it-works" aria-labelledby="process-title">
        <div className="section-container landing-process-inner">
          <div className="landing-process-heading">
            <p className="landing-overline">Simple by design</p>
            <h2 id="process-title">Go from idea<br />to <span>action.</span></h2>
            <p>Keep the search lightweight and the reasoning visible, so your team can move with confidence.</p>
            <Link className="landing-button landing-button-outline" to="/signup">Start with a brief <span aria-hidden="true">→</span></Link>
          </div>
          <div className="landing-steps">
            {steps.map((step) => (
              <article className="landing-step" key={step.number}>
                <span className="landing-step-number">{step.number}</span>
                <div><h3>{step.title}</h3><p>{step.copy}</p></div>
                <span className="landing-step-arrow" aria-hidden="true">↗</span>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="landing-cta section-container">
        <div className="landing-cta-panel">
          <div className="landing-cta-orb" aria-hidden="true" />
          <div>
            <p className="landing-overline">Make your next search count</p>
            <h2>Find the fit.<br /><span>Make the move.</span></h2>
          </div>
          <div className="landing-cta-action">
            <p>Start with the brief you already have.</p>
            <Link className="landing-button" to="/signup">Create your workspace <span aria-hidden="true">→</span></Link>
            <span className="landing-cta-login">Already have an account? <Link to="/login">Sign in</Link></span>
          </div>
        </div>
      </section>

      <footer className="landing-footer section-container">
        <a className="landing-brand" href="#top" aria-label="Spark home"><img src="/logo-mark.png" alt="" width={28} height={28} /><span>Spark</span></a>
        <span>Better matches, made actionable.</span>
        <div><Link to="/login">Sign in</Link><Link to="/signup">Create account</Link></div>
      </footer>
    </main>
  );
}

function ProductPreview() {
  return (
    <div className="product-preview">
      <div className="preview-chrome">
        <div className="preview-window-controls"><i /><i /><i /></div>
        <div className="preview-address"><span className="preview-lock">⌑</span> app.spark.match / creators</div>
        <span className="preview-user">AM</span>
      </div>
      <div className="preview-app">
        <div className="preview-app-head">
          <div className="preview-mini-brand"><img src="/logo-mark.png" alt="" /> <b>Spark</b></div>
          <div className="preview-tabs"><span className="selected">Creators</span><span>Companies</span></div>
          <span className="preview-menu">•••</span>
        </div>
        <div className="preview-heading"><span>NEW MATCH</span><div>Creator search <b>↗</b></div></div>
        <div className="preview-prompt"><span>YOUR BRIEF</span><p>Thoughtful skincare creators for sensitive skin and a younger audience…</p><div className="preview-chips"><i>Instagram</i><i>Audience: 18–34</i><i>English</i></div></div>
        <div className="preview-results-head"><strong>Shortlist</strong><span>Best fit <b>⌄</b></span></div>
        <PreviewCreator initials="JM" name="Jules Martin" handle="@julesmakes" category="Beauty · Skincare" score="92" tone="blue" />
        <PreviewCreator initials="AR" name="Ari Rivera" handle="@skinwithari" category="Wellness · Lifestyle" score="87" tone="violet" />
        <div className="preview-bottom"><span><i /> Reasons tied to profile details</span><span>Compare shortlist <b>→</b></span></div>
      </div>
    </div>
  );
}

function PreviewCreator({ initials, name, handle, category, score, tone }: { initials: string; name: string; handle: string; category: string; score: string; tone: "blue" | "violet" }) {
  return (
    <div className="preview-creator">
      <div className={`preview-avatar avatar-${tone}`}>{initials}</div>
      <div className="preview-creator-info"><b>{name}</b><span>{handle} <i>·</i> {category}</span></div>
      <div className="preview-score"><strong>{score}</strong><span>FIT</span></div>
    </div>
  );
}

function CreatorVisual() {
  return (
    <div className="creator-visual" aria-hidden="true">
      <div className="creator-visual-header"><span>CREATOR FIT</span><span className="visual-live"><i /> SAMPLE</span></div>
      <div className="creator-visual-profile"><div className="creator-visual-avatar">JM</div><div><b>Jules Martin</b><small>Beauty · Skincare</small></div><strong>92<small>FIT</small></strong></div>
      <div className="creator-visual-divider" />
      <div className="visual-stat-row"><div><small>AVG. REACH</small><b>18.4k</b></div><div><small>ENGAGEMENT</small><b>4.8%</b></div><div><small>AUDIENCE</small><b>18–34</b></div></div>
      <div className="visual-reason"><span>✳</span><p><b>Strong content fit</b><br />Skincare education appears throughout the creator’s profile.</p></div>
    </div>
  );
}

function CompanyVisual() {
  return (
    <div className="company-visual" aria-hidden="true">
      <div className="company-visual-header"><span>COMPANY FIT</span><span className="visual-live"><i /> SAMPLE</span></div>
      <div className="company-visual-profile"><div className="company-mark">N</div><div><b>Northstar Labs</b><small>Supply chain software</small></div><span className="company-stage">SERIES A</span></div>
      <div className="company-signal-title">WHY IT MATCHES</div>
      <div className="company-signals"><span><i>✓</i> Growing logistics team</span><span><i>✓</i> Hiring across operations</span><span><i>✓</i> Expanding into new markets</span></div>
      <div className="company-visual-footer"><span>TEAM SIZE <b>51–200</b></span><span>GROWTH <b>↑ Rising</b></span></div>
    </div>
  );
}
