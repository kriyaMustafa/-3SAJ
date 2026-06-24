/* @refresh reload */
import { render } from 'solid-js/web'
import './index.css'
import App from './App.jsx'
import { AppProvider } from './AppContext.jsx'

const root = document.getElementById('root')

render(() => (
  <AppProvider>
    <App />
  </AppProvider>
), root)
