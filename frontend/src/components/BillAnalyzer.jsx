import React, { useState, useEffect, createContext, useContext } from 'react';
import { Socket, io } from 'socket.io-client';
import { Sun, Moon, Download, AlertTriangle } from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import DownloadMenu from './dropdown-menu.jsx'; 

// Create ThemeContext
const ThemeContext = createContext('light');

const BillAnalyzer = () => {
  const [billNumber, setBillNumber] = useState('');
  const [isProcessing, setIsProcessing] = useState(false);
  const [currentStep, setCurrentStep] = useState(0);
  const [progress, setProgress] = useState({ current: 0, total: 0 });
  const [error, setError] = useState(null);
  const [reportUrl, setReportUrl] = useState(null);
  const [socket, setSocket] = useState(null);
  const [theme, setTheme] = useState(localStorage.getItem('theme') || 'light'); // Added theme state

  const steps = [
    { id: 1, name: 'Fetching Bill Text', description: 'Retrieving bill content from legislature website' },
    { id: 2, name: 'Initial Parsing', description: 'Breaking down bill into components' },
    { id: 3, name: 'Building Analysis Structure', description: 'Creating framework for analysis' },
    { id: 4, name: 'AI Analysis', description: 'Analyzing changes and impacts' },
    { id: 5, name: 'Report Generation', description: 'Creating final report' }
  ];

  useEffect(() => {
    // Initialize socket connection
    const socketUrl = window.location.protocol === 'https:'
      ? 'https://' + window.location.hostname
      : 'http://localhost:8080';

    const newSocket = io(socketUrl, {
      transports: ['websocket', 'polling'],
      reconnectionAttempts: 5,
      reconnectionDelay: 1000,
      secure: true
    });

    newSocket.on('connect', () => {
      console.log('Connected to server');
    });

    newSocket.on('connect_error', (error) => {
      console.error('Socket connection error:', error);
      setError('Failed to connect to analysis server');
    });

    setSocket(newSocket);

    // Set up socket event listeners
    newSocket.on('analysis_progress', (data) => {
      setCurrentStep(data.step);
      if (data.total_substeps > 0) {
        setProgress({
          current: data.current_substep,
          total: data.total_substeps
        });
      }
    });

    newSocket.on('analysis_complete', (data) => {
      setIsProcessing(false);
      setReportUrl(data.report_url);
    });

    newSocket.on('analysis_error', (data) => {
      setError(data.error);
      setIsProcessing(false);
    });

    // Cleanup on unmount
    return () => {
      newSocket.close();
    };
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setIsProcessing(true);
    setCurrentStep(1);
    setError(null);
    setReportUrl(null);

    try {
      console.log('Sending request to analyze bill:', billNumber);
      const response = await fetch('/api/analyze', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ billNumber })
      });

      console.log('Response status:', response.status);

      if (!response.ok) {
        const data = await response.json();
        console.error('Error response:', data);
        throw new Error(data.error || 'Failed to start analysis');
      }

      const data = await response.json();
      console.log('Success response:', data);
    } catch (err) {
      console.error('Error details:', err);
      setError(err.message || 'Failed to connect to server');
      setIsProcessing(false);
    }
  };

  const handleDownload = async () => {
    if (reportUrl) {
      window.open(reportUrl, '_blank');
    }
  };

  const toggleTheme = () => {
    const newTheme = theme === 'light' ? 'dark' : 'light';
    setTheme(newTheme);
    localStorage.setItem('theme', newTheme);
    document.documentElement.classList.toggle('dark');
  };

  return (
    <ThemeContext.Provider value={theme}> {/* Added ThemeContext Provider */}
    <div className={`min-h-screen p-8 ${theme === 'dark' ? 'dark' : ''}`}>
      <div className="max-w-4xl mx-auto">
        <div className="flex justify-between items-center mb-8">
          <h1 className="text-3xl font-bold">Trailer Bill Analyzer</h1>
          <button
            onClick={toggleTheme}
            className={`p-2 rounded-full hover:bg-gray-200 dark:hover:bg-gray-700 ${theme === 'dark' ? 'text-gray-200' : 'text-gray-700'}`}
          >
            {theme === 'dark' ? <Sun size={24} /> : <Moon size={24} />}
          </button>
        </div>

        {error && (
          <Alert variant="destructive" className="mb-6">
            <AlertTriangle className="h-4 w-4" />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <form onSubmit={handleSubmit} className="mb-8">
          <div className="flex gap-4">
            <input
              type="text"
              value={billNumber}
              onChange={(e) => setBillNumber(e.target.value)}
              placeholder="Enter Bill Number (e.g., AB173)"
              className="flex-1 p-3 border rounded-lg text-gray-900"
              disabled={isProcessing}
            />
            <button
              type="submit"
              disabled={isProcessing || !billNumber}
              className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
            >
              Analyze Bill
            </button>
          </div>
        </form>

        {isProcessing && (
          <div className="space-y-6">
            <div className="bg-white dark:bg-gray-800 rounded-lg p-6 shadow-lg">
              <ol className="relative border-l border-gray-300 dark:border-gray-700 ml-3">
                {steps.map((step, index) => {
                  const isActive = currentStep === step.id;
                  const isComplete = currentStep > step.id;
                  return (
                    <li key={step.id} className="mb-6 ml-4">
                      <div className="absolute w-3 h-3 rounded-full mt-1.5 -left-1.5 border border-gray-300 dark:border-gray-700">
                        <div
                          className={`w-full h-full rounded-full ${
                            isComplete ? 'bg-green-500' :
                            isActive ? 'bg-blue-500 animate-pulse' :
                            'bg-gray-300 dark:bg-gray-700'
                          }`}
                        />
                      </div>
                      <div className={`${
                        isActive ? 'text-blue-600 dark:text-blue-400' :
                        isComplete ? 'text-green-600 dark:text-green-400' :
                        'text-gray-500 dark:text-gray-400'
                      }`}>
                        <h3 className="font-semibold">{step.name}</h3>
                        <p className="text-sm">{step.description}</p>
                        {isActive && step.id === 4 && progress.total > 0 && (
                          <div className="mt-2">
                            <div className="text-sm mb-1">
                              Analyzing section {progress.current} of {progress.total}
                            </div>
                            <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-2.5">
                              <div
                                className="bg-blue-600 h-2.5 rounded-full transition-all duration-500"
                                style={{ width: `${(progress.current / progress.total) * 100}%` }}
                              />
                            </div>
                          </div>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ol>
            </div>
          </div>
        )}

        {reportUrl && (
          <div className="flex justify-center mt-6">
            <DownloadMenu reportUrl={reportUrl} />
          </div>
        )}
      </div>
    </div>
    </ThemeContext.Provider>
  );
};

export default BillAnalyzer;