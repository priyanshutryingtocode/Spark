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
          <div className="lp-nav-links">
            <a href="#product">Product</a>
            <a href="#method">How it works</a>
          </div>
          <a className="lp-brand" href="#top" aria-label="Spark home">
            <img src="/logo-mark.png" alt="" width={30} height={30} />
            <span>Spark</span>
          </a>
          <div className="lp-nav-actions">
            <Link className="lp-nav-signin" to="/login">Sign in</Link>
            <Link className="lp-button lp-button--small" to="/signup">Get started</Link>
          </div>
        </nav>
      </header>

      <section className="lp-wrap lp-hero" id="top" aria-labelledby="lp-title">
        <h1 id="lp-title">From a rough brief to a shortlist you can defend.</h1>
        <p className="lp-lead">
          Describe the creators your campaign needs, or the early-stage companies that fit your ICP.
          Spark ranks the candidates and shows the evidence behind each match.
        </p>
        <div className="lp-actions">
          <Link className="lp-button" to="/signup">Create your workspace</Link>
          <a className="lp-link" href="#method">See how it works</a>
        </div>
        <ProductPreview />
      </section>

      <section className="lp-product" id="product" aria-labelledby="lp-product-title">
        <div className="lp-wrap">
          <div className="lp-section-head">
            <h2 id="lp-product-title">Good matches start with the whole picture.</h2>
            <p>
              Move past one-size-fits-all filters. Search the context around a match, then see what
              makes each candidate worth a closer look.
            </p>
          </div>
          <div className="lp-spec">
            <article className="lp-offer" aria-labelledby="lp-spec-creators">
              <h3 id="lp-spec-creators">Find creators who feel right for your brand.</h3>
              <p className="lp-offer-copy">Match on content, audience, reach, and campaign intent, not follower count alone.</p>
              <CreatorSample />
              <dl className="lp-facets">
                <div><dt>Content</dt><dd>What the creator posts about</dd></div>
                <div><dt>Audience</dt><dd>Who follows them</dd></div>
                <div><dt>Reach</dt><dd>How far their posts travel</dd></div>
                <div><dt>Campaign intent</dt><dd>Whether the profile suits your goal</dd></div>
              </dl>
              <Link className="lp-link" to="/signup">Start a creator search</Link>
            </article>
            <article className="lp-offer" aria-labelledby="lp-spec-companies">
              <h3 id="lp-spec-companies">Find emerging companies that fit your ICP.</h3>
              <p className="lp-offer-copy">Surface companies by what they do, their stage, their size, and the needs they signal.</p>
              <CompanySample />
              <dl className="lp-facets">
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
        <div className="lp-wrap lp-method-grid">
          <div className="lp-method-intro">
            <h2 id="lp-method-title">Go from idea to action.</h2>
            <p>Keep the search lightweight and the reasoning visible, so your team can move with confidence.</p>
            <Link className="lp-button lp-button--outline" to="/signup">Start with a brief</Link>
          </div>
          <ol className="lp-steps">
            {steps.map((step, i) => (
              <li className="lp-step" key={step.title}>
                <span className="lp-step-num" aria-hidden="true">{i + 1}</span>
                <div>
                  <h3>{step.title}</h3>
                  <p>{step.copy}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="lp-cta" aria-labelledby="lp-cta-title">
        <div className="lp-wrap lp-cta-inner">
          <h2 id="lp-cta-title">Set a brief.</h2>
          <div className="lp-cta-body">
            <p>Describe the fit in plain language and review a ranked shortlist with the reasons attached.</p>
            <div className="lp-actions">
              <Link className="lp-button" to="/signup">Create your workspace</Link>
            </div>
            <p className="lp-cta-login">Already have an account? <Link className="lp-link" to="/login">Sign in</Link></p>
          </div>
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
      <div className="lp-frame">
      <div className="lp-window" role="group" aria-label="Sample preview of Spark’s matching workspace">
        <div className="lp-app-head">
          <div className="lp-app-brand">
            <img src="/logo-mark.png" alt="" width={24} height={24} />
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
            <strong>Search</strong>
            <span>{current.subtitle}</span>
          </div>

          <div className="lp-app-body">
            <div className="lp-app-brief">
              <p className="lp-label">Brief</p>
              <p className="lp-field-label">{current.question}</p>
              <div className="lp-textarea">
                {current.brief.map((segment, i) =>
                  typeof segment === "string" ? (
                    <Fragment key={i}>{segment}</Fragment>
                  ) : (
                    <mark className="lp-mark" key={i} style={delayStyle(0.2 + segment.n * 0.3)}>{segment.text}</mark>
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
                <p className="lp-label">Shortlist</p>
                <span className="lp-sort">Best fit</span>
              </div>
              <div className="lp-results">
                {current.results.map((result, i) => (
                  <div className="lp-result" key={result.name}>
                    <div className="lp-avatar lp-avatar--lg">{result.initials}</div>
                    <div className="lp-result-info">
                      <b>{result.name}</b>
                      <span className="lp-result-meta">
                        <span>{result.handle}</span>
                        <span>{result.category}</span>
                      </span>
                      <span className="lp-bar"><i style={{ width: `${result.score}%`, ...delayStyle(1.3 + i * 0.15) }} /></span>
                    </div>
                    <div className="lp-result-score"><strong>{result.score}</strong><span>fit</span></div>
                  </div>
                ))}
              </div>
              <div className="lp-app-bottom">
                <span>{current.reasons}</span>
                <span className="lp-app-bottom-action">Compare shortlist</span>
              </div>
            </div>
          </div>
        </div>
      </div>
      </div>
      <p className="lp-preview-caption">Product preview with sample data.</p>
    </div>
  );
}

function CreatorSample() {
  return (
    <figure className="lp-sample">
      <figcaption>Example match, sample data</figcaption>
      <div className="lp-sample-head">
        <span className="lp-avatar lp-avatar--lg">JM</span>
        <div><b>Jules Martin</b><span>Beauty and skincare</span></div>
        <strong className="lp-sample-score">92<small>fit</small></strong>
      </div>
      <dl className="lp-sample-facts">
        <div><dt>Average reach</dt><dd>18.4k</dd></div>
        <div><dt>Engagement</dt><dd>4.8%</dd></div>
        <div><dt>Audience</dt><dd>18–34</dd></div>
      </dl>
      <div className="lp-sample-reason">
        <b>Why it matches</b>
        <ul>
          <li>Skincare education across recent posts</li>
          <li>Content for sensitive skin</li>
          <li>Audience aged 18–34</li>
        </ul>
      </div>
    </figure>
  );
}

function CompanySample() {
  return (
    <figure className="lp-sample">
      <figcaption>Example match, sample data</figcaption>
      <div className="lp-sample-head">
        <span className="lp-avatar lp-avatar--lg">NL</span>
        <div><b>Northstar Labs</b><span>Supply chain software</span></div>
        <span className="lp-sample-stage">Series A</span>
      </div>
      <dl className="lp-sample-facts">
        <div><dt>Team size</dt><dd>51–200</dd></div>
        <div><dt>Growth</dt><dd>Rising</dd></div>
      </dl>
      <div className="lp-sample-reason">
        <b>Why it matches</b>
        <ul>
          <li>Growing logistics team</li>
          <li>Hiring across operations</li>
          <li>Expanding into new markets</li>
        </ul>
      </div>
    </figure>
  );
}
