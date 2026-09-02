PRAGMA foreign_keys = ON;

CREATE TABLE offers (
  offer_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  offer_type TEXT NOT NULL,
  category TEXT NOT NULL,
  country_code TEXT NOT NULL DEFAULT 'US',
  region TEXT,
  city TEXT,
  venue TEXT,
  price_amount REAL,
  currency TEXT,
  price_note TEXT,
  valid_from TEXT,
  valid_to TEXT,
  booking_end TEXT,
  availability_status TEXT NOT NULL,
  eligibility_tier TEXT NOT NULL,
  eligibility_text TEXT,
  source_url TEXT NOT NULL,
  visual_page_url TEXT NOT NULL,
  direct_image_url TEXT,
  source_method TEXT NOT NULL,
  confidence TEXT NOT NULL,
  last_verified_at TEXT NOT NULL,
  notes TEXT
);

CREATE TABLE offer_tags (
  offer_id TEXT NOT NULL REFERENCES offers(offer_id) ON DELETE CASCADE,
  tag TEXT NOT NULL,
  PRIMARY KEY (offer_id, tag)
);

CREATE INDEX idx_offers_location ON offers(country_code, region, city);
CREATE INDEX idx_offers_category ON offers(category, offer_type);
CREATE INDEX idx_offers_dates ON offers(valid_to, booking_end);
CREATE INDEX idx_offers_status ON offers(availability_status);
CREATE INDEX idx_tags_tag ON offer_tags(tag);

CREATE VIEW active_offers AS
SELECT * FROM offers
WHERE availability_status IN ('AVAILABLE','LIMITED','WAITLIST','SURFACED')
  AND (valid_to IS NULL OR valid_to >= date('now'))
  AND (booking_end IS NULL OR booking_end >= date('now'));

CREATE VIEW alex_relevant_offers AS
SELECT o.*, COUNT(t.tag) AS alex_signal_count
FROM offers o
JOIN offer_tags t ON t.offer_id = o.offer_id
WHERE t.tag IN ('alex','nyc','vegas','miami','orlando','family','dining','sports','running','football','golf','culture','entertainment')
GROUP BY o.offer_id
ORDER BY alex_signal_count DESC, o.city, o.title;
