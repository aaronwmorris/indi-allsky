import { IconSet } from "./index.js";
import { findMatchingIcon } from "./match.js";
import { hasIconDataBeenModified } from "./modified.js";

function assertNever(v) {}
/**
* Merge icon sets
*/
function mergeIconSets(oldIcons, newIcons) {
	const mergedIcons = new IconSet(newIcons.export());
	const oldEntries = oldIcons.entries;
	const entries = mergedIcons.entries;
	function add(name) {
		if (entries[name]) return true;
		const item = oldEntries[name];
		switch (item.type) {
			case "icon": {
				const fullIcon = oldIcons.resolve(name, true);
				const parent = fullIcon ? findMatchingIcon(mergedIcons, fullIcon) : null;
				if (parent !== null) {
					mergedIcons.setAlias(name, parent);
					return true;
				}
				const props = item.props;
				mergedIcons.setItem(name, {
					...item,
					props: {
						...props,
						hidden: true
					},
					categories: /* @__PURE__ */ new Set()
				});
				return true;
			}
			case "variation":
			case "alias": {
				let parent = item.parent;
				if (!add(parent)) return false;
				const parentItem = entries[parent];
				if (parentItem.type === "alias") parent = parentItem.parent;
				if (item.type === "variation") {
					const props = item.props;
					mergedIcons.setItem(name, {
						...item,
						parent,
						props: {
							...props,
							hidden: true
						}
					});
				} else mergedIcons.setItem(name, {
					...item,
					parent
				});
				return true;
			}
			default:
				assertNever(item);
				return false;
		}
	}
	for (const name in oldEntries) add(name);
	if (oldIcons.lastModified && !hasIconDataBeenModified(oldIcons, mergedIcons)) mergedIcons.updateLastModified(oldIcons.lastModified);
	else if (newIcons.lastModified && !hasIconDataBeenModified(newIcons, mergedIcons)) mergedIcons.updateLastModified(newIcons.lastModified);
	return mergedIcons;
}

export { mergeIconSets };