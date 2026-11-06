/**
 * Website & Online Menu Scraper for Guinness Detection
 * Crawls a venue's website homepage + discovered menu/drinks subpages
 * and parses menu text for Guinness variants and pricing.
 */

const MENU_PATH_PATTERNS = /menu|drink|beer|draught|draft|tap|bar|beverage|food|wine|carta/i;

const GUINNESS_VARIANTS = [
  { pattern: /guinness\s*0\.?0|guinness\s*zero|non[-\s]*alcoholic\s*guinness/i, label: 'Guinness 0.0 (Alcohol-Free)' },
  { pattern: /guinness\s*foreign\s*extra/i, label: 'Guinness Foreign Extra Stout' },
  { pattern: /guinness\s*extra\s*stout/i, label: 'Guinness Extra Stout' },
  { pattern: /guinness\s*west\s*indies/i, label: 'Guinness West Indies Porter' },
  { pattern: /guinness\s*extra\s*cold/i, label: 'Guinness Extra Cold' },
  { pattern: /guinness\s*nitrosurge|nitro\s*surge/i, label: 'Guinness Nitrosurge' },
  { pattern: /guinness\s*draught|guinness\s*on\s*tap|draught\s*guinness|pint\s*of\s*guinness/i, label: 'Guinness Draught (On Tap)' },
  { pattern: /\bguinness\b/i, label: 'Guinness Stout' },
];

const PRICE_REGEX = /(?:CHF|Fr\.|€|£|\$)\s*\d{1,2}(?:[.,]\d{2}|[.,]-)?|\d{1,2}[.,]\d{2}\s*(?:CHF|Fr\.|€|£|\$)/gi;

function stripHtmlToLines(html) {
  return html
    .replace(/<script[\s\S]*?<\/script>/gi, ' ')
    .replace(/<style[\s\S]*?<\/style>/gi, ' ')
    .replace(/<\/(p|div|li|tr|h1|h2|h3|h4|h5|h6|section|article|br|dd|dt)>/gi, '\n')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/gi, ' ')
    .replace(/&amp;/gi, '&')
    .replace(/&euro;/gi, '€')
    .replace(/&pound;/gi, '£')
    .split('\n')
    .map((line) => line.replace(/\s+/g, ' ').trim())
    .filter((line) => line.length > 2);
}

function extractMenuLinks(html, baseUrl) {
  const links = new Set();
  const hrefRegex = /href=["']([^"'#]+)["']/gi;
  let match;
  while ((match = hrefRegex.exec(html)) !== null) {
    const rawHref = match[1].trim();
    if (!rawHref || rawHref.startsWith('mailto:') || rawHref.startsWith('tel:') || rawHref.startsWith('javascript:')) {
      continue;
    }
    if (MENU_PATH_PATTERNS.test(rawHref)) {
      try {
        const resolved = new URL(rawHref, baseUrl);
        if (resolved.origin === new URL(baseUrl).origin) {
          links.add(resolved.href);
        }
      } catch {
        // Ignore malformed URLs
      }
    }
  }
  return Array.from(links).slice(0, 4);
}

async function fetchHtmlWithTimeout(url, timeoutMs = 6500) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, {
      signal: controller.signal,
      headers: {
        'User-Agent':
          'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
        Accept: 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
      },
    });
    if (!response.ok) return null;
    const contentType = response.headers.get('content-type') || '';
    if (!contentType.includes('text/html') && !contentType.includes('text/plain')) {
      return null;
    }
    return await response.text();
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

export async function scrapeVenueMenuForGuinness(websiteUrl, existingDemoCheck = null) {
  if (!websiteUrl) {
    return {
      checked: false,
      lastChecked: new Date().toISOString(),
      foundOnMenu: false,
      typesFound: [],
      extractedPrice: null,
      snippets: ['No website URL available for this venue.'],
      scannedUrls: [],
    };
  }

  let normalizedUrl = websiteUrl.trim();
  if (!/^https?:\/\//i.test(normalizedUrl)) {
    normalizedUrl = `https://${normalizedUrl}`;
  }

  const scannedUrls = [normalizedUrl];
  const homeHtml = await fetchHtmlWithTimeout(normalizedUrl);

  // If network is unavailable or the demo domain doesn't resolve live, return enriched scan or fallback
  if (!homeHtml) {
    if (existingDemoCheck && existingDemoCheck.checked) {
      return {
        ...existingDemoCheck,
        lastChecked: new Date().toISOString(),
        scannedUrls: [normalizedUrl],
        mode: 'cached-menu-snapshot',
      };
    }
    return {
      checked: true,
      lastChecked: new Date().toISOString(),
      foundOnMenu: false,
      typesFound: [],
      extractedPrice: null,
      snippets: [`Could not reach ${normalizedUrl} directly (site may block bots or require browser rendering).`],
      scannedUrls,
      mode: 'unreachable',
    };
  }

  const subMenuLinks = extractMenuLinks(homeHtml, normalizedUrl);
  const subPagesHtml = await Promise.all(
    subMenuLinks.map(async (link) => {
      scannedUrls.push(link);
      return await fetchHtmlWithTimeout(link);
    })
  );

  const allPagesHtml = [homeHtml, ...subPagesHtml.filter(Boolean)];
  const typesFoundSet = new Set();
  const snippets = [];
  let extractedPrice = null;

  for (const pageHtml of allPagesHtml) {
    const lines = stripHtmlToLines(pageHtml);
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (/guinness/i.test(line)) {
        for (const variant of GUINNESS_VARIANTS) {
          if (variant.pattern.test(line)) {
            typesFoundSet.add(variant.label);
          }
        }
        // Check current line or adjacent line for a price
        const contextWindow = [lines[i - 1] || '', line, lines[i + 1] || ''].join(' — ').trim();
        const priceMatches = contextWindow.match(PRICE_REGEX);
        if (priceMatches && !extractedPrice) {
          extractedPrice = priceMatches[0].trim();
        }
        const cleanSnippet = line.length > 180 ? `${line.slice(0, 177)}...` : line;
        if (!snippets.includes(cleanSnippet) && snippets.length < 5) {
          snippets.push(cleanSnippet);
        }
      }
    }
  }

  const foundOnMenu = typesFoundSet.size > 0 || snippets.length > 0;
  if (foundOnMenu && typesFoundSet.size === 0) {
    typesFoundSet.add('Guinness Draught (On Tap)');
  }

  return {
    checked: true,
    lastChecked: new Date().toISOString(),
    foundOnMenu,
    typesFound: Array.from(typesFoundSet),
    extractedPrice,
    snippets: foundOnMenu
      ? snippets
      : [`Scanned ${scannedUrls.length} page(s) on ${new URL(normalizedUrl).hostname} — no explicit "Guinness" text found on public HTML menu.`],
    scannedUrls,
    mode: 'live-scrape',
  };
}
