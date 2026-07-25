function mergeSet(set) {
	return set ? Array.from(set).sort((a, b) => a.localeCompare(b)).join("") : "";
}
/**
* Convert selector parts to string
*/
function stringifySelectorSubParts(selector, isSVG = false) {
	const combinator = selector.combinator ? `& ${selector.combinator} ` : "";
	const tag = isSVG ? "" : `${selector.tag || ""}${selector.id || ""}`;
	const attr = `${mergeSet(selector.name)}${mergeSet(selector.attr)}`;
	const pseudo = mergeSet(selector.pseudo);
	const full = `${tag}${attr}${pseudo}`;
	if (isSVG) return full ? `${combinator}svg${full}` : combinator.trim();
	return `${combinator}${pseudo && full === pseudo ? "*" : ""}${full}`;
}
export { stringifySelectorSubParts };
