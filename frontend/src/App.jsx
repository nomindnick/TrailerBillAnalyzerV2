// src/App.jsx
import React from 'react';
import BillAnalyzer from './components/BillAnalyzer';
import { ThemeProvider } from './lib/ThemeProvider';

function App() {
  return (
    <ThemeProvider>
      {/* The .dark class is toggled on <html> by ThemeProvider */}
      <div className="app min-h-screen transition-colors duration-200">
        <BillAnalyzer />
      </div>
    </ThemeProvider>
  );
}

export default App;
