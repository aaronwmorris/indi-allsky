/**
* Split rules string into object
*/
function splitCSSRules(rules) {
	if (typeof rules === "string") {
		const result = Object.create(null);
		const parts = rules.split(";");
		for (const part of parts) {
			const [key, value] = part.split(":").map((s) => s.trim());
			if (key && value) result[key] = value;
		}
		return result;
	}
	return rules;
}
/**
* Merge rules
*/
function mergeCSSRules(rules, oldRules) {
	return {
		...splitCSSRules(oldRules || {}),
		...splitCSSRules(rules)
	};
}
export { mergeCSSRules, splitCSSRules };
