const reservedStateNames = new Set([
	"constructor",
	"class",
	"in",
	"of",
	"if",
	"for",
	"while",
	"switch",
	"case",
	"break",
	"continue",
	"default",
	"do",
	"else",
	"finally",
	"return",
	"throw",
	"try",
	"catch",
	"with",
	"yield",
	"async",
	"await",
	"static",
	"using",
	"function",
	"var",
	"let",
	"const",
	"this",
	"import",
	"export",
	"props",
	"classname",
	"viewbox",
	"fallback",
	"states",
	"width",
	"height",
	"size",
	"square"
]);
/**
* Validates states list to avoid issues when generating icons
*/
function assertValidStatesList(list) {
	for (const state of list) {
		const stateName = typeof state === "string" ? state : state[0];
		if (!stateName.match(/^[a-z$]+$/)) throw new Error(`Invalid state name "${stateName}".`);
		if (reservedStateNames.has(stateName)) throw new Error(`State name "${stateName}" is reserved to avoid conflicts and cannot be used.`);
	}
}
export { assertValidStatesList };
