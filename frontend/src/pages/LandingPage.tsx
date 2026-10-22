import { Fragment, useState, type CSSProperties, type KeyboardEvent, type ReactNode } from "react";
import { Link, Navigate } from "react-router-dom";

import { useAuth } from "../auth/AuthProvider";
import "./landing.css";

const steps = [
  { title: "Describe the fit", copy: "Write what you need in your own words. Add audience, industry, size, or budget requirements when they matter." },
  { title: "Review the shortlist", copy: "Spark finds relevant creators or companies, ranks the candidates, and shows the reasons behind each match." },
  { title: "Move forward", copy: "Compare candidates, revisit past searches, and export the shortlist for your next step." },
];

type PreviewId = "creators" | "companies";
type Segment = string | { text: string; n: number };

interface PreviewResult {
  initials: string;
  name: string;
  handle: string;
  category: string;
  score: number;
}

interface Preview {
  id: PreviewId;
  label: string;
  subtitle: string;
  question: string;
  brief: Segment[];
  suggestions: string[];
  results: PreviewResult[];
  reasons: string;
}

const PREVIEWS: Preview[] = [
  {
    id: "creators",
    label: "Creators",
    subtitle: "Look up creators based on your requirements.",
    question: "What are you promoting?",
    brief: [
      "Thoughtful ",
      { text: "skincare creators", n: 1 },
      " for ",
      { text: "sensitive skin", n: 2 },
      " and a ",
      { text: "younger audience", n: 3 },
      ", on Instagram and in English.",
    ],
    suggestions: [
      "a thrifted-vintage clothing label for Gen Z who care about slow fashion",
      "budget-friendly travel planning for solo backpackers",
      "data-driven investing basics for first-time buyers",
    ],
    results: [
      { initials: "JM", name: "Jules Martin", handle: "@julesmakes", category: "Beauty, skincare", score: 92 },
      { initials: "AR", name: "Ari Rivera", handle: "@skinwithari", category: "Wellness, lifestyle", score: 87 },
    ],
    reasons: "Reasons tied to profile details",
  },
  {
    id: "companies",
    label: "Companies",
    subtitle: "Look up companies based on your requirements.",
    question: "Who are you prospecting?",
    brief: [
      "Early-stage ",
      { text: "logistics software", n: 1 },
      " companies with ",
      { text: "50 to 200 people", n: 2 },
      " that are ",
      { text: "hiring in operations", n: 3 },
      ", in North America.",
    ],
    suggestions: [
      "payroll tools for small hospitality teams",
      "climate analytics for commercial real estate",
      "security software for regional credit unions",
    ],
    results: [
      { initials: "NL", name: "Northstar Labs", handle: "Supply chain software", category: "Series A", score: 91 },
      { initials: "LS", name: "Ledgerway Systems", handle: "Freight billing software", category: "Series A", score: 84 },
    ],
    reasons: "Reasons tied to company signals",
  },
];

const delayStyle = (seconds: number) => ({ "--d": `${seconds}s` }) as CSSProperties;

function Icon({ children }: { children: ReactNode }) {
  return (
    <svg className="lp-icon" viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {children}
    </svg>
  );
}

export function LandingPage() {
  const { session, loading } = useAuth();
  if (loading) {
    return (
      <main className="lp-loading" aria-busy="true">
        <img src="/logo-mark.png" alt="" width={36} height={36} />
        <span>Opening Spark…</span>
      </main>
    );
  }
  if (session) return <Navigate to="/creators/search" replace />;

  return (
    <main className="lp-page">
      <header className="lp-header">
        <nav className="lp-wrap lp-nav" aria-label="Main navigation">
          <a className="lp-brand" href="#top" aria-label="Spark home">
            <img src="/logo-mark.png" alt="" width={34} height={34} />
            <span>Spark</span>
          </a>
          <div className="lp-nav-links">
            <a href="#product">Product</a>
            <a href="#method">How it works</a>
          </div>
          <div className="lp-nav-actions">
            <Link className="lp-nav-signin" to="/login">Sign in</Link>
            <Link className="lp-button lp-button--small" to="/signup">Get started</Link>
          </div>
        </nav>
      </header>

      <section className="lp-wrap lp-hero" id="top" aria-labelledby="lp-title">
        <p className="lp-eyebrow lp-hero-eyebrow">Creator and company matching</p>
        <h1 id="lp-title">From a rough brief to a shortlist you can defend.</h1>
        <div className="lp-hero-aside">
          <p>
            Describe the creators your campaign needs, or the early-stage companies that fit your ICP.
            Spark ranks the candidates and shows the evidence behind each match.
          </p>
          <div className="lp-actions">
            <Link className="lp-button" to="/signup">Create your workspace</Link>
            <a className="lp-link" href="#method">See how it works</a>
          </div>
        </div>
        <ProductPreview />
      </section>

      <section className="lp-product" id="product" aria-labelledby="lp-product-title">
        <div className="lp-wrap lp-grid">
          <div className="lp-product-intro">
            <p className="lp-eyebrow">Product</p>
            <h2 id="lp-product-title">Good matches start with the whole picture.</h2>
            <p>
              Move past one-size-fits-all filters. Search the context around a match, then see what
              makes each candidate worth a closer look.
            </p>
          </div>
          <div className="lp-spec">
            <article className="lp-card" aria-labelledby="lp-spec-creators">
              <p className="lp-eyebrow">Creator matching</p>
              <h3 id="lp-spec-creators">Find creators who feel right for your brand.</h3>
              <p className="lp-card-copy">Match on content, audience, reach, and campaign intent, not follower count alone.</p>
              <CreatorVisual />
              <dl>
                <div><dt>Content</dt><dd>What the creator posts about</dd></div>
                <div><dt>Audience</dt><dd>Who follows them</dd></div>
                <div><dt>Reach</dt><dd>How far their posts travel</dd></div>
                <div><dt>Campaign intent</dt><dd>Whether the profile suits your goal</dd></div>
              </dl>
              <Link className="lp-link" to="/signup">Start a creator search</Link>
            </article>
            <article className="lp-card" aria-labelledby="lp-spec-companies">
              <p className="lp-eyebrow">Company matching</p>
              <h3 id="lp-spec-companies">Find emerging companies that fit your ICP.</h3>
              <p className="lp-card-copy">Surface companies by what they do, their stage, their size, and the needs they signal.</p>
              <CompanyVisual />
              <dl>
                <div><dt>What they do</dt><dd>The product and the market</dd></div>
                <div><dt>Stage</dt><dd>How far along they are</dd></div>
                <div><dt>Size</dt><dd>Team headcount</dd></div>
                <div><dt>Signals</dt><dd>Needs they show, such as hiring</dd></div>
              </dl>
              <Link className="lp-link" to="/signup">Start a company search</Link>
            </article>
          </div>
        </div>
      </section>

      <section className="lp-method" id="method" aria-labelledby="lp-method-title">
        <div className="lp-wrap lp-grid">
          <div className="lp-method-intro">
            <p className="lp-eyebrow">How it works</p>
            <h2 id="lp-method-title">Go from idea to action.</h2>
            <p>Keep the search lightweight and the reasoning visible, so your team can move with confidence.</p>
            <Link className="lp-button lp-button--outline" to="/signup">Start with a brief</Link>
          </div>
          <ol className="lp-steps">
            {steps.map((step, i) => (
              <li className="lp-step" key={step.title}>
                <span className="lp-step-num" aria-hidden="true">{String(i + 1).padStart(2, "0")}</span>
                <div>
                  <h3>{step.title}</h3>
                  <p>{step.copy}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="lp-wrap lp-cta" aria-labelledby="lp-cta-title">
        <div className="lp-cta-panel">
          <p className="lp-eyebrow">Ready</p>
          <h2 id="lp-cta-title">Set a brief.</h2>
          <p className="lp-cta-copy">Describe the fit in plain language and review a ranked shortlist with the reasons attached.</p>
          <ul className="lp-stages" aria-label="What happens next">
            <li>Describe</li>
            <li>Rank</li>
            <li>Compare</li>
            <li>Export</li>
          </ul>
          <Link className="lp-button" to="/signup">Create your workspace</Link>
          <span className="lp-cta-login">Already have an account? <Link className="lp-link" to="/login">Sign in</Link></span>
        </div>
      </section>

      <footer className="lp-footer">
        <div className="lp-wrap lp-footer-inner">
          <a className="lp-brand lp-brand--small" href="#top" aria-label="Spark home">
            <img src="/logo-mark.png" alt="" width={26} height={26} />
            <span>Spark</span>
          </a>
          <span>Better matches, made actionable.</span>
          <div className="lp-footer-links">
            <Link to="/login">Sign in</Link>
            <Link to="/signup">Create account</Link>
          </div>
        </div>
      </footer>
    </main>
  );
}

function ProductPreview() {
  const [active, setActive] = useState<PreviewId>("creators");
  const current = PREVIEWS.find((p) => p.id === active) ?? PREVIEWS[0];
  const briefLength = current.brief.reduce((total, s) => total + (typeof s === "string" ? s.length : s.text.length), 0);

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    event.preventDefault();
    const index = PREVIEWS.findIndex((p) => p.id === active);
    const step = event.key === "ArrowRight" ? 1 : -1;
    const next = PREVIEWS[(index + step + PREVIEWS.length) % PREVIEWS.length];
    setActive(next.id);
    document.getElementById(`lp-tab-${next.id}`)?.focus();
  };

  return (
    <div className="lp-preview">
      <div className="lp-window" role="group" aria-label="Sample preview of Spark’s matching workspace">
        <div className="lp-chrome">
          <div className="lp-chrome-dots" aria-hidden="true"><i /><i /><i /></div>
          <div className="lp-chrome-address">app.spark.match/{active}/search</div>
          <span className="lp-chrome-spacer" aria-hidden="true" />
        </div>

        <div className="lp-app-head">
          <div className="lp-app-brand">
            <img src="/logo-mark.png" alt="" width={26} height={26} />
            <b>Spark</b>
          </div>
          <div className="lp-seg" role="tablist" aria-label="Sample searches">
            {PREVIEWS.map((preview) => (
              <button
                key={preview.id}
                id={`lp-tab-${preview.id}`}
                className="lp-seg-tab"
                type="button"
                role="tab"
                aria-selected={preview.id === active}
                aria-controls="lp-panel"
                tabIndex={preview.id === active ? 0 : -1}
                onClick={() => setActive(preview.id)}
                onKeyDown={onKeyDown}
              >
                {preview.label}
              </button>
            ))}
          </div>
          <div className="lp-app-nav" aria-hidden="true">
            <span className="is-current"><Icon><circle cx="11" cy="11" r="6" /><path d="M20 20l-4.2-4.2" /></Icon>Search</span>
            <span><Icon><circle cx="12" cy="12" r="8" /><path d="M12 8v4l3 2" /></Icon>History</span>
            <span><Icon><path d="M4 7h13M13 3l4 4-4 4M20 17H7M11 13l-4 4 4 4" /></Icon>Compare</span>
          </div>
          <span className="lp-avatar" aria-hidden="true">AM</span>
        </div>

        <div id="lp-panel" role="tabpanel" aria-labelledby={`lp-tab-${active}`} key={active}>
          <div className="lp-app-title">
            <p className="lp-eyebrow">New match</p>
            <strong>Search</strong>
            <span>{current.subtitle}</span>
          </div>

          <div className="lp-app-body">
            <div className="lp-app-brief">
              <p className="lp-eyebrow">Brief</p>
              <p className="lp-field-label">{current.question}</p>
              <div className="lp-textarea">
                {current.brief.map((segment, i) =>
                  typeof segment === "string" ? (
                    <Fragment key={i}>{segment}</Fragment>
                  ) : (
                    <mark className="lp-mark" key={i} style={delayStyle(0.3 + segment.n * 0.4)}>{segment.text}</mark>
                  ),
                )}
              </div>
              <p className="lp-counter">{briefLength}/600</p>
              <div className="lp-pills">
                {current.suggestions.map((suggestion) => (
                  <span className="lp-pill" key={suggestion}>{suggestion}</span>
                ))}
              </div>
            </div>

            <div className="lp-app-results">
              <div className="lp-results-head">
                <p className="lp-eyebrow">Shortlist</p>
                <span className="lp-sort">Best fit</span>
              </div>
              {current.results.map((result, i) => (
                <div className="lp-result" key={result.name}>
                  <div className={i === 0 ? "lp-avatar lp-avatar--lg" : "lp-avatar lp-avatar--lg lp-avatar--tint"}>{result.initials}</div>
                  <div className="lp-result-info">
                    <b>{result.name}</b>
                    <span className="lp-result-meta">
                      <span>{result.handle}</span>
                      <span className="lp-result-cat">{result.category}</span>
                    </span>
                    <span className="lp-bar"><i style={{ width: `${result.score}%`, ...delayStyle(0.5 + i * 0.2) }} /></span>
                  </div>
                  <div className="lp-result-score"><strong>{result.score}</strong><span>fit</span></div>
                </div>
              ))}
              <div className="lp-app-bottom">
                <span><i aria-hidden="true" />{current.reasons}</span>
                <span className="lp-app-bottom-action">Compare shortlist</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="lp-float-note">
        <span className="lp-float-check" aria-hidden="true">✓</span>
        <span><strong>Why it fits</strong><small>Evidence alongside every match</small></span>
      </div>
      <p className="lp-preview-caption"><span className="lp-dot" aria-hidden="true" />Product preview, sample data</p>
    </div>
  );
}

function CreatorVisual() {
  return (
    <div className="lp-visual" aria-hidden="true">
      <div className="lp-visual-head"><span>Creator fit</span><span className="lp-sample-tag"><i />Sample</span></div>
      <div className="lp-visual-profile">
        <div className="lp-avatar lp-avatar--lg">JM</div>
        <div><b>Jules Martin</b><small>Beauty and skincare</small></div>
        <strong className="lp-visual-score">92<small>fit</small></strong>
      </div>
      <div className="lp-stats">
        <div><small>Average reach</small><b>18.4k</b></div>
        <div><small>Engagement</small><b>4.8%</b></div>
        <div><small>Audience</small><b>18–34</b></div>
      </div>
      <div className="lp-reason">
        <span>✳</span>
        <p><b>Strong content fit</b>Skincare education appears throughout the creator’s profile.</p>
      </div>
    </div>
  );
}

function CompanyVisual() {
  return (
    <div className="lp-visual" aria-hidden="true">
      <div className="lp-visual-head"><span>Company fit</span><span className="lp-sample-tag"><i />Sample</span></div>
      <div className="lp-visual-profile">
        <div className="lp-company-mark">N</div>
        <div><b>Northstar Labs</b><small>Supply chain software</small></div>
        <span className="lp-stage">Series A</span>
      </div>
      <div className="lp-visual-title">Why it matches</div>
      <ul className="lp-signals">
        <li><i>✓</i>Growing logistics team</li>
        <li><i>✓</i>Hiring across operations</li>
        <li><i>✓</i>Expanding into new markets</li>
      </ul>
      <div className="lp-visual-foot">
        <span>Team size <b>51–200</b></span>
        <span>Growth <b>↑ Rising</b></span>
      </div>
    </div>
  );
}