const uniqueKeys = ["tag", "id"];
const mergeKeys = [
	"name",
	"attr",
	"pseudo"
];
/**
* Merge multiple selector parts into one
*/
function mergeMultipleSelectorSubParts(parts) {
	const result = {};
	for (const part of parts) {
		if (part.combinator) {
			if (!result.combinator) result.combinator = part.combinator;
			else if (result.combinator !== part.combinator) return null;
		}
		for (const key of uniqueKeys) {
			const value = part[key];
			if (value) {
				if (result[key] && result[key] !== value) return null;
				result[key] = value;
			}
		}
		for (const key of mergeKeys) {
			const values = part[key];
			if (values) {
				const list = result[key] || /* @__PURE__ */ new Set();
				if (!result[key]) result[key] = list;
				for (const value of values) list.add(value);
			}
		}
	}
	return result;
}
export { mergeMultipleSelectorSubParts };
