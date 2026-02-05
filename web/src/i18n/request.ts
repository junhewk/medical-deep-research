import { getRequestConfig } from 'next-intl/server';
import { defaultLocale, type Locale } from './config';

export default getRequestConfig(async () => {
  // In a real app, you'd detect locale from cookies/headers
  // For now, we'll use the default and let client-side handle switching
  const locale: Locale = defaultLocale;

  return {
    locale,
    messages: (await import(`../../messages/${locale}.json`)).default,
  };
});
