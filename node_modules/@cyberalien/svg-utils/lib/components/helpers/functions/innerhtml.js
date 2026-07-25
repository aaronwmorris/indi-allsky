import { addCustomFunctionAsset } from "./custom.js";
const functionName = "cleanupHTML";
/**
* Adds cleanUpInnerHTML() function to assets
*/
function addInnerHTMLFunctionAsset(imports, assets, options) {
	addCustomFunctionAsset(imports, assets, options, {
		functionName,
		content: `let policy;

function createPolicy() {
	try {
		policy = window.trustedTypes.createPolicy('iconify', {
			createHTML: (s) => s,
		});
	} catch (err) {
		policy = null;
	}
}

export function ${functionName}(html) {
	if (policy === undefined) {
		createPolicy();
	}

	return policy ? policy.createHTML(html) : html;
}
`,
		jsName: "innerhtml"
	});
	return functionName;
}
export { addInnerHTMLFunctionAsset };
