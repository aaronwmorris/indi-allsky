import { getIconifyIconSetDefaults } from "./defaults.js";
/**
* Get icon data from Iconify icon set
*/
function getIconifyIconSetIcon(data, name) {
	if (data.not_found?.includes(name)) return null;
	const icon = data.icons[name];
	if (icon) return {
		...getIconifyIconSetDefaults(data),
		...icon
	};
	const alias = data.aliases?.[name];
	if (alias) {
		const parentIcon = data.icons?.[alias.parent];
		return parentIcon ? {
			...getIconifyIconSetDefaults(data),
			...parentIcon,
			...alias
		} : null;
	}
}
export { getIconifyIconSetIcon };
