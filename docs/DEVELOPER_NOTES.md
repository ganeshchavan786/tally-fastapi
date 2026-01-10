# Developer Notes - Tally Database Loader

## Company Period Auto-Detection

### Overview
The sync page automatically extracts financial year period from company names when Tally API doesn't provide `books_from` and `books_to` data.

### How It Works

#### 1. Company Name Pattern: `YY-YY` (e.g., "18-24")
Many Tally companies include financial year in their name:
- `MATOSHRI ENTERPRISES 18-24` → Apr 2018 to Mar 2024
- `Vrushali Infotech Pvt Ltd. 25-26` → Apr 2025 to Mar 2026

**Logic:**
```javascript
// Pattern: /(\d{2})-(\d{2})$/
// "18-24" → from: 2018-04-01, to: 2024-03-31
```

#### 2. Company Name Pattern: `(from D-Mon-YY)` 
Some companies have start date in name:
- `Test23131131313131sdfd - (from 1-Sep-25)` → Sep 2025 to Mar 2026

**Logic:**
```javascript
// Pattern: /\(from\s+(\d{1,2})-([A-Za-z]{3})-(\d{2})\)/i
// "(from 1-Sep-25)" → from: 2025-09-01, to: 2026-03-31
```

#### 3. Fallback: Default Period
If no pattern matches:
- Default From: `2025-04-01`
- Default To: `2026-03-31`

### Code Location
- **Frontend:** `static/js/sync.js` - `extractPeriodFromName()` function
- **Backend:** `app/services/tally_service.py` - `_parse_company_list_with_period()`

### Tally API Limitation

**Issue:** Tally's "List of Companies" collection doesn't always return `BOOKSFROM` data.

**Expected XML Response:**
```xml
<COMPANY NAME="CompanyName">
    <BOOKSFROM>20180401</BOOKSFROM>
    <STARTINGFROM>20180401</STARTINGFROM>
    <COMPANYNUMBER>100001</COMPANYNUMBER>
</COMPANY>
```

**Actual Response:** Often returns empty `BOOKSFROM` field.

**Workaround:** Extract period from company name pattern.

### Future Improvement
To get accurate period from Tally, use TDL report with company-specific query:
```xml
<FIELD NAME="FldBooksFrom">
    <SET>$BooksFrom</SET>
</FIELD>
```

This requires selecting each company individually and querying its info.

---

## Sync Page Features

### 1. Synced Companies Hidden
- Only NEW (unsynced) companies shown in list
- Synced companies checked via `/api/data/synced-companies` endpoint

### 2. Per-Company Actions
Each company row has:
- **Checkbox** - Select for batch sync
- **Period Display** - Auto-extracted or editable
- **Pencil Button** - Edit period manually
- **Sync Button** - Full sync for that company

### 3. Period Edit Modal
Users can manually edit period via pencil button:
- Opens modal with From/To date inputs
- Saves to `companyPeriods` object
- Updates display immediately

---

## API Endpoints Used

| Endpoint | Purpose |
|----------|---------|
| `/api/companies` | Get companies from Tally |
| `/api/data/synced-companies` | Get synced companies from DB |
| `/api/sync/full` | Start full sync |
| `/api/sync/status` | Get sync progress |

---

## File Structure

```
static/
├── sync.html          # Sync page HTML
├── dashboard.html     # Dashboard page
├── audit.html         # Audit trail page
├── css/
│   ├── common.css     # Shared styles (light theme)
│   ├── sync.css       # Sync page styles
│   ├── dashboard.css  # Dashboard styles
│   └── audit.css      # Audit page styles
└── js/
    ├── common.js      # Shared functions (API, toast, etc.)
    ├── sync.js        # Sync page logic
    ├── dashboard.js   # Dashboard logic
    └── audit.js       # Audit page logic
```

---

## Known Issues

1. **Tally Period Not Returned:** Tally API doesn't return `books_from` in collection request
2. **Company Name Parsing:** Only works for standard naming patterns

## Contributing
When adding new features:
1. Follow existing code style
2. Add developer notes for complex logic
3. Test with multiple company name formats
