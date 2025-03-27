// frontend/src/components/BillAnalyzer.jsx

import React, { useState, useEffect, useRef } from 'react';
import { io } from 'socket.io-client';
import { Sun, Moon, AlertTriangle, CheckCircle2, FileSearch, ChevronRight, Sparkles } from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import DownloadMenu from './DownloadMenu';
import { useTheme } from '../lib/ThemeProvider';
import AnalysisProgress from './AnalysisProgress';

export default function BillAnalyzer() {
  const [billNumber, setBillNumber] = useState('');
  const [sessionYear, setSessionYear] = useState('2023-2024');
  const [error, setError] = useState(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [startTime, setStartTime] = useState(null);
  const [elapsedTime, setElapsedTime] = useState(null);
  const [reportUrl, setReportUrl] = useState(null);
  const [currentStep, setCurrentStep] = useState(0);
  const [stepMessage, setStepMessage] = useState('');
  const [progress, setProgress] = useState({ current: 0, total: 0 });
  const [stepProgressMap, setStepProgressMap] = useState({});
  const [expandedStepId, setExpandedStepId] = useState(null);
  const { theme, toggleTheme } = useTheme();
  const [model, setModel] = useState('o3-mini-2025-01-31');
  const [animateForm, setAnimateForm] = useState(false);

  // Socket management
  const [socketConnected, setSocketConnected] = useState(false);
  const socketRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  const [currentAnalysisId, setCurrentAnalysisId] = useState(null);

  // Analysis steps definition
  const analysisSteps = [
    { id: 1, name: "Fetching Bill", description: "Retrieving bill text from legislature database" },
    { id: 2, name: "Parsing Text", description: "Extracting sections and digest items" },
    { id: 3, name: "Building Analysis Structure", description: "Creating structured data for analysis" },
    { id: 4, name: "Matching Bill Sections", description: "Connecting digest items to bill sections" },
    { id: 5, name: "Analyzing Impacts", description: "Evaluating effects on public agencies" }, 
    { id: 6, name: "Generating Report", description: "Creating the final analysis report" }
  ];

  // Add entrance animation when component mounts
  useEffect(() => {
    setAnimateForm(true);
  }, []);

  // Timer for elapsed time
  useEffect(() => {
    let timer;
    if (isProcessing && startTime) {
      timer = setInterval(() => {
        setElapsedTime(formatElapsedTime(startTime, Date.now()));
      }, 1000);
    }
    return () => clearInterval(timer);
  }, [isProcessing, startTime]);

  // Socket connection management
  const connectSocket = () => {
    if (socketRef.current) {
      console.log('Cleaning up existing socket');
      socketRef.current.disconnect();
    }

    console.log('Connecting to socket at:', window.location.origin);
    const socket = io(window.location.origin, {
      path: '/socket.io',
      transports: ['websocket'],
      reconnection: true,
      reconnectionAttempts: 5,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 5000,
      timeout: 20000
    });

    socket.on('connect', () => {
      console.log('Socket connected successfully with ID:', socket.id);
      setSocketConnected(true);
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }
    });

    socket.on('connection_established', (data) => {
      console.log('Connection established:', data);
    });

    socket.on('disconnect', (reason) => {
      console.log('Socket disconnected:', reason);
      setSocketConnected(false);

      // Only attempt reconnect if we're still processing
      if (isProcessing && !reconnectTimeoutRef.current) {
        reconnectTimeoutRef.current = setTimeout(() => {
          console.log('Attempting to reconnect...');
          connectSocket();
        }, 1000);
      }
    });

    socket.on('analysis_progress', (data) => {
      console.log('Progress update received:', data);

      // Only process updates for current analysis
      if (!currentAnalysisId || data.analysis_id === currentAnalysisId) {
        // Update step information if provided
        if (data.step !== undefined) {
          setCurrentStep(data.step);
          if (data.message) {
            setStepMessage(data.message);
          }
        }

        // Update substep progress if provided
        if (data.current_substep !== undefined) {
          setProgress({
            current: data.current_substep,
            total: data.total_substeps || progress.total // Keep existing total if not provided
          });

          // If there's a specific message for this substep
          if (data.message) {
            setStepMessage(data.message);
          }
        }
      }
    });

    socket.on('analysis_complete', (data) => {
      console.log('Analysis complete:', data);
      if (!currentAnalysisId || data.analysis_id === currentAnalysisId) {
        setReportUrl(data.report_url);
        setIsProcessing(false);
        setError(null);
      }
    });

    socket.on('analysis_error', (data) => {
      console.error('Analysis error:', data);
      setError(data.error || 'An error occurred during analysis');
      setIsProcessing(false);
    });

    socket.on('pong', (data) => {
      console.log('Received pong:', data);
    });

    socketRef.current = socket;
  };

  // Connect socket on mount
  useEffect(() => {
    connectSocket();
    return () => {
      console.log('Cleaning up socket connection');
      if (socketRef.current) {
        socketRef.current.disconnect();
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
    };
  }, []);

  // Keep connection alive with ping/pong
  useEffect(() => {
    const pingInterval = setInterval(() => {
      if (socketRef.current?.connected && isProcessing) {
        socketRef.current.emit('ping', { timestamp: Date.now() });
      }
    }, 10000);

    return () => clearInterval(pingInterval);
  }, [isProcessing]);

  const onToggleExpand = (stepId) => {
    if (expandedStepId === stepId) {
      setExpandedStepId(null);
    } else {
      setExpandedStepId(stepId);
    }
  };

  const analyzeBill = async () => {
    if (!billNumber) {
      setError('Please enter a bill number');
      return;
    }

    try {
      // Reset state
      setError(null);
      setIsProcessing(true);
      const now = Date.now();
      setStartTime(now);
      setReportUrl(null);
      setCurrentStep(1);
      setStepMessage('Starting bill analysis');
      setProgress({ current: 0, total: 0 });
      setStepProgressMap({});
      setExpandedStepId(null);

      // Generate unique analysis ID
      const analysisId = `analysis_${now}`;
      setCurrentAnalysisId(analysisId);

      // Ensure socket is connected
      if (!socketRef.current?.connected) {
        console.log('Socket not connected, reconnecting...');
        connectSocket();
        // Wait for connection
        await new Promise((resolve) => {
          const checkConnection = setInterval(() => {
            if (socketRef.current?.connected) {
              clearInterval(checkConnection);
              resolve();
            }
          }, 100);
        });
      }

      console.log('Sending request to analyze bill:', billNumber, 'from session:', sessionYear, 'using model:', model);

      const response = await fetch('/api/analyze', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          billNumber,
          sessionYear,
          model,
          analysisId
        }),
      });

      console.log('Response status:', response.status);
      const data = await response.json();
      console.log('Analysis started successfully:', data);

      if (!response.ok) {
        throw new Error(data.error || 'Failed to start analysis');
      }

    } catch (err) {
      console.error('Error starting analysis:', err);
      setError(err.message || 'Failed to start analysis');
      setIsProcessing(false);
    }
  };

  // Available session years - add new ones at the top as they become available
  const availableSessionYears = [
    '2025-2026',
    '2023-2024',
    '2021-2022',
    '2019-2020',
    '2017-2018'
  ];

  const modelOptions = [
    'o3-mini-2025-01-31', 
    'gpt-4o-2024-08-06',
    'claude-3-sonnet-20240229'
  ];

  return (
    <div className="min-h-screen bg-gradient-to-b from-blue-50 to-white dark:from-gray-900 dark:to-gray-800 transition-all duration-500">
      <div className="container mx-auto px-4 py-12">
        <header className="flex justify-between items-center mb-12">
          <div className="flex items-center gap-3">
            <FileSearch className="w-8 h-8 text-blue-600 dark:text-blue-400" />
            <h1 className="text-3xl font-bold bg-gradient-to-r from-blue-600 to-purple-600 dark:from-blue-400 dark:to-purple-400 bg-clip-text text-transparent">
              Trailer Bill Analyzer
            </h1>
          </div>
          <button
            onClick={toggleTheme}
            className="p-3 rounded-full bg-white dark:bg-gray-800 shadow-md hover:shadow-lg transition-all duration-300 text-blue-600 dark:text-blue-400"
          >
            {theme === 'dark' ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
          </button>
        </header>

        <div 
          className={`space-y-8 transform transition-all duration-500 ${
            animateForm ? 'translate-y-0 opacity-100' : 'translate-y-4 opacity-0'
          }`}
        >
          <div className="bg-white dark:bg-gray-800 p-6 rounded-xl shadow-lg transition-all duration-300">
            <h2 className="text-xl font-semibold mb-4 text-gray-800 dark:text-gray-200">
              Enter Bill Information
            </h2>

            <div className="flex flex-col md:flex-row gap-4">
              <div className="flex-1">
                <label htmlFor="billNumber" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Bill Number
                </label>
                <div className="relative">
                  <input
                    id="billNumber"
                    type="text"
                    value={billNumber}
                    onChange={(e) => setBillNumber(e.target.value.toUpperCase())}
                    placeholder="e.g., AB173"
                    className="w-full p-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 placeholder-gray-400 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all duration-200"
                    disabled={isProcessing}
                  />
                </div>
              </div>

              <div className="md:w-48">
                <label htmlFor="sessionYear" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Session Year
                </label>
                <select
                  id="sessionYear"
                  value={sessionYear}
                  onChange={(e) => setSessionYear(e.target.value)}
                  className="w-full p-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all duration-200"
                  disabled={isProcessing}
                >
                  {availableSessionYears.map(year => (
                    <option key={year} value={year}>{year}</option>
                  ))}
                </select>
              </div>

              <div className="md:w-64">
                <label htmlFor="model" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  AI Model
                </label>
                <select
                  id="model"
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  className="w-full p-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all duration-200"
                  disabled={isProcessing}
                >
                  {modelOptions.map(option => (
                    <option key={option} value={option}>
                      {option === 'o3-mini-2025-01-31' ? 'GPT-o3-mini (January 2025)' : 
                       option === 'gpt-4o-2024-08-06' ? 'GPT-4o (August 2024)' : 
                       'Claude 3.7 Extended Reasoning'}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="mt-6">
              <button
                onClick={analyzeBill}
                disabled={isProcessing || !billNumber}
                className={`w-full md:w-auto px-6 py-3 flex items-center justify-center gap-2 rounded-lg font-medium transition-all duration-300 ${
                  isProcessing || !billNumber
                    ? 'bg-gray-300 text-gray-500 cursor-not-allowed dark:bg-gray-700 dark:text-gray-400'
                    : 'bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-700 hover:to-indigo-700 text-white shadow-md hover:shadow-lg'
                }`}
              >
                {isProcessing ? (
                  <>
                    <div className="animate-spin w-5 h-5 border-2 border-white border-opacity-20 border-t-white rounded-full" />
                    Analyzing...
                  </>
                ) : (
                  <>
                    <Sparkles className="h-5 w-5" />
                    Analyze Bill
                  </>
                )}
              </button>
            </div>
          </div>

          {error && (
            <Alert variant="destructive" className="animate-shake bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800">
              <AlertTriangle className="h-5 w-5 text-red-600 dark:text-red-400" />
              <AlertDescription className="ml-2">{error}</AlertDescription>
            </Alert>
          )}

          {isProcessing && (
            <div className="space-y-4 animate-fade-in">
              <AnalysisProgress
                currentStep={currentStep}
                stepMessage={stepMessage}
                steps={analysisSteps}
                progress={stepProgressMap[currentStep] || progress}
                startTime={startTime}
                stepProgress={stepProgressMap}
                expandedStepId={expandedStepId}
                onToggleExpand={onToggleExpand}
              />
              <div className="flex items-center justify-center gap-2 py-2 text-blue-600 dark:text-blue-400">
                <div className="animate-pulse w-3 h-3 bg-blue-600 dark:bg-blue-400 rounded-full" />
                <p className="text-sm font-medium">
                  Time elapsed: {elapsedTime || '0s'}
                </p>
              </div>
            </div>
          )}

          {reportUrl && (
            <div className="bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 p-6 rounded-xl shadow-md animate-bounce-in">
              <div className="flex items-center gap-3 mb-4">
                <div className="bg-green-100 dark:bg-green-800 rounded-full p-2">
                  <CheckCircle2 className="h-6 w-6 text-green-600 dark:text-green-400" />
                </div>
                <h3 className="text-xl font-semibold text-green-800 dark:text-green-400">Analysis Complete!</h3>
              </div>

              <p className="text-gray-700 dark:text-gray-300 mb-4">
                Your bill analysis has been completed successfully. The report is ready for viewing or download.
              </p>

              <div className="flex items-center gap-3">
                <DownloadMenu reportUrl={reportUrl} />
                <a 
                  href={reportUrl} 
                  target="_blank" 
                  rel="noopener noreferrer" 
                  className="inline-flex items-center gap-2 px-4 py-2 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
                >
                  View Report
                  <ChevronRight className="h-4 w-4" />
                </a>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// Helper function to format elapsed time
const formatElapsedTime = (start, now) => {
  const elapsedMs = now - start;
  const seconds = Math.floor(elapsedMs / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);

  if (hours > 0) {
    return `${hours}h ${minutes % 60}m ${seconds % 60}s`;
  } else if (minutes > 0) {
    return `${minutes}m ${seconds % 60}s`;
  } else {
    return `${seconds}s`;
  }
};