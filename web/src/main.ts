import { createApp } from 'vue'
import { createPinia } from 'pinia'
import {
  ElAlert,
  ElAside,
  ElButton,
  ElCheckbox,
  ElCollapse,
  ElCollapseItem,
  ElContainer,
  ElDatePicker,
  ElDescriptions,
  ElDescriptionsItem,
  ElDialog,
  ElDivider,
  ElDrawer,
  ElDropdown,
  ElDropdownItem,
  ElDropdownMenu,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElHeader,
  ElIcon,
  ElInput,
  ElInputNumber,
  ElLoading,
  ElMain,
  ElMenu,
  ElMenuItem,
  ElMenuItemGroup,
  ElOption,
  ElPagination,
  ElRadio,
  ElRadioButton,
  ElRadioGroup,
  ElSelect,
  ElSwitch,
  ElTabPane,
  ElTable,
  ElTableColumn,
  ElTabs,
  ElTag,
  ElTooltip,
  ElUpload,
} from 'element-plus'
import 'element-plus/dist/index.css'
import App from './App.vue'
import router from './router'
import './style.css'

const app = createApp(App)
app.use(createPinia())
app.use(router)
const elementComponents = [
  ElAlert, ElAside, ElButton, ElCheckbox, ElCollapse, ElCollapseItem, ElContainer, ElDatePicker,
  ElDescriptions, ElDescriptionsItem, ElDialog, ElDivider, ElDrawer, ElDropdown,
  ElDropdownItem, ElDropdownMenu, ElEmpty,
  ElForm, ElFormItem, ElHeader, ElIcon, ElInput, ElInputNumber, ElMain, ElMenu,
  ElMenuItem, ElMenuItemGroup, ElOption, ElPagination, ElRadio, ElRadioButton, ElRadioGroup,
  ElSelect, ElSwitch, ElTabPane, ElTable, ElTableColumn, ElTabs, ElTag, ElTooltip,
  ElUpload,
]
for (const component of elementComponents) {
  app.use(component)
  // Some Element Plus children expose no-op installers.
  if (component.name && !app.component(component.name)) app.component(component.name, component)
}
app.use(ElLoading)
app.mount('#app')
