import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import { initialLanguage, messages, saveLanguage, type Language, type MessageKey } from "./i18n";

interface LanguageContextValue {
  language: Language;
  setLanguage: (language: Language) => void;
  t: (key: MessageKey) => string;
}

const LanguageContext = createContext<LanguageContextValue | null>(null);

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [language, setLanguageState] = useState<Language>(initialLanguage);
  const value = useMemo<LanguageContextValue>(
    () => ({
      language,
      setLanguage: (next: Language) => {
        saveLanguage(next);
        setLanguageState(next);
        document.documentElement.lang = next === "zh" ? "zh-CN" : "en";
      },
      t: (key: MessageKey) => messages[language][key],
    }),
    [language],
  );
  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export function useLanguage(): LanguageContextValue {
  const value = useContext(LanguageContext);
  if (!value) throw new Error("useLanguage must be used inside LanguageProvider");
  return value;
}
