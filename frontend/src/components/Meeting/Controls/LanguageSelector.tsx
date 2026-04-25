// components/Meeting/Controls/LanguageSelector.tsx
'use client';

const SUPPORTED_LANGUAGES = [
  { code: 'en', name: '🇬🇧 English', short: 'EN' },
  { code: 'vi', name: '🇻🇳 Tiếng Việt', short: 'VI' },
  { code: 'zh', name: '🇨🇳 中文', short: 'ZH' },
  { code: 'ja', name: '🇯🇵 日本語', short: 'JA' },
  { code: 'ko', name: '🇰🇷 한국어', short: 'KO' },
  { code: 'fr', name: '🇫🇷 Français', short: 'FR' },
  { code: 'de', name: '🇩🇪 Deutsch', short: 'DE' },
  { code: 'es', name: '🇪🇸 Español', short: 'ES' },
  { code: 'ru', name: '🇷🇺 Русский', short: 'RU' },
  { code: 'th', name: '🇹🇭 ไทย', short: 'TH' },
  { code: 'hi', name: '🇮🇳 हिन्दी', short: 'HI' },
  { code: 'it', name: '🇮🇹 Italiano', short: 'IT' },
  { code: 'pt', name: '🇵🇹 Português', short: 'PT' },
  { code: 'nl', name: '🇳🇱 Nederlands', short: 'NL' },
  { code: 'pl', name: '🇵🇱 Polski', short: 'PL' },
  { code: 'tr', name: '🇹🇷 Türkçe', short: 'TR' },
  { code: 'id', name: '🇮🇩 Indonesia', short: 'ID' },
  { code: 'ar', name: '🇸🇦 العربية', short: 'AR' },
];

interface LanguageSelectorProps {
  value: string;
  onChange: (value: string) => void;
  isTranslating?: boolean;
}

export const LanguageSelector: React.FC<LanguageSelectorProps> = ({
  value,
  onChange,
  isTranslating = false
}) => {
  return (
    <div className="flex items-center gap-2 p-2 bg-gradient-to-r from-blue-50 to-indigo-50 rounded-lg border border-blue-200">
      <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4 text-blue-600 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path strokeLinecap="round" strokeLinejoin="round" d="M3 5h12M9 3v2m1.048 9.5A18.022 18.022 0 016.412 9m6.088 9h7M11 21l5-10 5 10M12.751 5C11.783 10.77 8.07 15.61 3 18.129" />
      </svg>
      <span className="text-xs font-medium text-blue-700 whitespace-nowrap">Dịch sang:</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="flex-1 px-2 py-1 text-sm border border-blue-300 rounded-md bg-white focus:outline-none focus:ring-1 focus:ring-blue-500"
      >
        {SUPPORTED_LANGUAGES.map(lang => (
          <option key={lang.code} value={lang.code}>
            {lang.name}
          </option>
        ))}
      </select>
      {isTranslating && (
        <div className="flex items-center gap-1">
          <svg className="animate-spin h-3 w-3 text-blue-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
          </svg>
        </div>
      )}
    </div>
  );
};