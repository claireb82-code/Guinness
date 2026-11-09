// The price to show for a venue, and whether anything checked it. A visitor's report or a price read from the venue's
// own website is "checked"; a price that only comes from the starter list is shown, but marked "unchecked".
export function priceDisplay(venue) {
  const checked = venue?.crowdCheck?.reportedPrice || venue?.menuCheck?.extractedPrice;
  if (checked) return { text: checked, checked: true };
  const hint = venue?.priceHint?.price;
  if (hint) return { text: hint, checked: false };
  return { text: null, checked: false };
}
