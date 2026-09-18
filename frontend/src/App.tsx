import { OverviewPage } from "./pages/OverviewPage";
import { PapersPage } from "./pages/PapersPage";
import { PaperDetailPage } from "./pages/PaperDetailPage";
import { ProvidersPage } from "./pages/ProvidersPage";
import { FailuresPage } from "./pages/FailuresPage";
import { LanguageProvider, useLanguage } from "./lib/LanguageContext";
import { api, type InstanceInfo } from "./lib/api";
import { useEffect, useState } from "react";

function CurrentPage() {
  const path = window.location.pathname;
  if (path.startsWith("/papers/")) return <PaperDetailPage paperId={path.split("/")[2]} />;
  if (path === "/papers") return <PapersPage />;
  if (path === "/providers") return <ProvidersPage />;
  if (path === "/failures") return <FailuresPage />;
  return <OverviewPage />;
}

function Shell() {
  const path = window.location.pathname;
  const { language, setLanguage, t } = useLanguage();
  const [instance, setInstance] = useState<InstanceInfo | null>(null);
  useEffect(() => {
    api.instance().then(setInstance).catch(() => setInstance(null));
  }, []);
  const navigation = [
    ["/", t("navOverview")],
    ["/papers", t("navPapers")],
    ["/providers", t("navProviders")],
    ["/failures", t("navFailures")],
  ];
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="/">
          <span className="brand-mark">LH</span>
          <span><strong>Literature</strong><small>{t("brandSubtitle")}</small></span>
        </a>
        <nav>
          {navigation.map(([href, label]) => (
            <a className={path === href || (href !== "/" && path.startsWith(href)) ? "active" : ""} href={href} key={href}>{label}</a>
          ))}
        </nav>
        <div className="language-switch" aria-label="Language">
          <button className={language === "zh" ? "active" : ""} onClick={() => setLanguage("zh")}>中文</button>
          <button className={language === "en" ? "active" : ""} onClick={() => setLanguage("en")}>EN</button>
        </div>
        <div className="sidebar-footer">
          <span className="local-instance-badge">{t("thisIsMyInstance")}</span>
          <span>{t("localFirst")} · v0.1.0</span>
          <span>127.0.0.1</span>
          {instance ? (
            <span className="mono instance-line" title={instance.project}>
              {instance.user}@{instance.hostname}
            </span>
          ) : null}
        </div>
      </aside>
      <main className="content">
        <CurrentPage />
      </main>
    </div>
  );
}

export default function App() {
  return (
    <LanguageProvider>
      <Shell />
    </LanguageProvider>
  );
}
