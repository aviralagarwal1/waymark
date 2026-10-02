import React from 'react'
import ReactDOM from 'react-dom/client'
import '@fontsource-variable/instrument-sans/wght.css'
import '@fontsource-variable/instrument-sans/wght-italic.css'
import App from './App'
import Auth from './Auth'
import type { AuthPage } from './Auth'
import Landing from './Landing'
import './styles.css'

// The landing page is the root, account pages sit beside it, and the
// workspace lives under /app. The server returns index.html for all of them,
// so this is the only routing there is.
const path = window.location.pathname.replace(/\/$/, '') || '/'
const authPages: AuthPage[] = ['signin', 'signup', 'verify', 'forgot', 'reset']
const authPage = authPages.find(page => path === `/${page}`)
const inApp = path === '/app' || path.startsWith('/app/')

ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode>{inApp ? <App /> : authPage ? <Auth page={authPage} /> : <Landing />}</React.StrictMode>)
