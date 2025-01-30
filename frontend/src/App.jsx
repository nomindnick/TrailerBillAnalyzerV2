
import React from 'react'
import BillAnalyzer from './components/BillAnalyzer'
import { ThemeProvider } from './lib/ThemeProvider'

function App() {
  return (
    <ThemeProvider>
      <div className="app min-h-screen transition-colors duration-200 dark:bg-gray-900">
        <BillAnalyzer />
      </div>
    </ThemeProvider>
  )
}

export default App
