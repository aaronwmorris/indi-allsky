import { getIconifyIconSetDefaults } from "./defaults.js";
/**
* Parse Iconify icon set and call callback for each icon
*/
function parseIconifyIconSet(data, callback) {
	const defaultValues = getIconifyIconSetDefaults(data);
	for (const name in data.icons) {
		const item = data.icons[name];
		callback(name, {
			...defaultValues,
			...item
		});
	}
	if (data.aliases) for (const name in data.aliases) {
		const item = data.aliases[name];
		const parentIcon = data.icons[item.parent];
		if (!parentIcon) {
			callback(name, null);
			continue;
		}
		callback(name, {
			...defaultValues,
			...parentIcon,
			...item
		});
	}
	if (data.not_found) for (const name of data.not_found) callback(name, null);
}
export { parseIconifyIconSet };
