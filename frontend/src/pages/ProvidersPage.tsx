import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useLanguage } from "../lib/LanguageContext";
import type { Provider } from "../types/api";
import { StatusBadge } from "../components/StatusBadge";

export function ProvidersPage() {
  const { t } = useLanguage();
  const [providers, setProviders] = useState<Provider[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.providers().then(setProviders).catch((reason: Error) => setError(reason.message));
  }, []);

  return (
    <div className="stack">
      <div className="page-heading">
        <div><p className="eyebrow">{t("providerTrail")}</p><h1>{t("navProviders")}</h1></div>
      </div>
      {error ? <div className="error-panel">{error}</div> : null}
      {providers.map((provider) => (
        <section className="card provider-card" key={provider.name}>
          <div className="provider-title">
            <div><h2>{provider.display_name}</h2><span className="mono">{provider.name}</span></div>
            <StatusBadge value={provider.health_status} />
          </div>
          <div className="credentials">
            {provider.credentials.map((credential) => (
              <div className="credential" key={credential.id}>
                <div><strong>{credential.label}</strong><span>{credential.institution ?? t("noInstitution")}</span></div>
                <StatusBadge value={credential.health} />
                <span className="scope">{credential.quota_scope} {t("scope")}</span>
              </div>
            ))}
            {provider.credentials.length === 0 ? <p className="empty">{t("noCredentials")}</p> : null}
          </div>
          {provider.services.map((service) => (
            <div className="service-block" key={service.name}>
              <div className="service-title">
                <h3>{service.name.replaceAll("_", " ")}</h3>
                <StatusBadge value={service.health_status} />
              </div>
              {service.quotas.map((quota) => (
                <div className="quota-row" key={quota.id}>
                  <div>
                    <strong>{quota.remaining ?? "?"} / {quota.limit ?? "?"}</strong>
                    <span>{quota.source === "local_estimate" ? "estimated" : quota.source.replaceAll("_", " ")}</span>
                  </div>
                  <div>
                    <span>{t("reset")} {quota.reset_at ? new Date(quota.reset_at).toLocaleString() : t("unknown")}</span>
                    <StatusBadge value={quota.status} />
                  </div>
                </div>
              ))}
              {service.quotas.length === 0 ? <p className="empty">{t("noQuota")}</p> : null}
            </div>
          ))}
        </section>
      ))}
    </div>
  );
}
