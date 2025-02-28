// src/components/AnalysisProgress.jsx

import React, { useState, useEffect } from 'react';
import { CheckCircle, Circle, Loader2, Clock } from 'lucide-react';

const AnalysisProgress = ({ currentStep, stepMessage, steps, progress, startTime }) => {
  const [elapsedTime, setElapsedTime] = useState('0s');
  
  // Update elapsed time every second
  useEffect(() => {
    if (!startTime) return;
    
    const formatTime = (start) => {
      const now = new Date();
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
    
    // Initial format
    setElapsedTime(formatTime(startTime));
    
    // Set up interval
    const intervalId = setInterval(() => {
      setElapsedTime(formatTime(startTime));
    }, 1000);
    
    // Clean up
    return () => clearInterval(intervalId);
  }, [startTime]);
  
  return (
    <div className="space-y-6 animate-fade-in">
      <div className="bg-white dark:bg-gray-800 rounded-lg p-6 shadow-lg transition-all">
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-xl font-semibold">Analysis Progress</h3>
          
          {/* Elapsed Time Display */}
          <div className="flex items-center text-blue-600 dark:text-blue-400 font-medium">
            <Clock className="w-4 h-4 mr-1" />
            <span>{elapsedTime}</span>
          </div>
        </div>

        {/* Step indicator */}
        <div className="w-full bg-gray-200 dark:bg-gray-700 h-2 mb-6 rounded-full overflow-hidden">
          <div 
            className="bg-blue-600 h-full rounded-full transition-all duration-500"
            style={{ width: `${(currentStep / steps.length) * 100}%` }}
          />
        </div>

        {/* Step message - shows the current operation */}
        {stepMessage && (
          <div className="p-3 bg-blue-50 dark:bg-blue-900/30 border border-blue-100 dark:border-blue-800 rounded mb-4 text-blue-800 dark:text-blue-200">
            <p className="text-sm">{stepMessage}</p>
          </div>
        )}

        {/* Detailed steps */}
        <ol className="relative border-l border-gray-300 dark:border-gray-700 ml-3 space-y-6">
          {steps.map((step) => {
            const isActive = currentStep === step.id;
            const isComplete = currentStep > step.id;

            return (
              <li key={step.id} className="ml-6">
                <span className="absolute flex items-center justify-center w-6 h-6 rounded-full -left-3 ring-8 ring-white dark:ring-gray-800">
                  {isComplete ? (
                    <CheckCircle className="w-5 h-5 text-green-500" />
                  ) : isActive ? (
                    <Loader2 className="w-5 h-5 text-blue-500 animate-spin" />
                  ) : (
                    <Circle className="w-5 h-5 text-gray-400 dark:text-gray-600" />
                  )}
                </span>

                <div className={`
                  p-4 rounded-lg border
                  ${isActive ? 'bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-800' : 
                    isComplete ? 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800' : 
                    'bg-gray-50 dark:bg-gray-900/20 border-gray-200 dark:border-gray-800'}
                  transition-all duration-200
                `}>
                  <h3 className={`font-medium ${
                    isActive ? 'text-blue-600 dark:text-blue-400' : 
                    isComplete ? 'text-green-600 dark:text-green-400' : 
                    'text-gray-500 dark:text-gray-400'
                  }`}>
                    {step.name}
                  </h3>

                  <p className="text-sm text-gray-600 dark:text-gray-300 mt-1">
                    {step.description}
                  </p>

                  {/* Substep progress bar for AI Analysis step */}
                  {isActive && step.id === 4 && progress.total > 0 && (
                    <div className="mt-3">
                      <div className="text-sm text-gray-600 dark:text-gray-300 mb-1 flex justify-between">
                        <span>Processing section {progress.current} of {progress.total}</span>
                        <span>{Math.round((progress.current / progress.total) * 100)}%</span>
                      </div>
                      <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-2">
                        <div
                          className="bg-blue-600 h-2 rounded-full transition-all duration-300"
                          style={{
                            width: `${(progress.current / progress.total) * 100}%`,
                          }}
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
  );
};

export default AnalysisProgress;