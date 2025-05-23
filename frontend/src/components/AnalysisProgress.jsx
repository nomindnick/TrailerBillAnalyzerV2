// src/components/AnalysisProgress.jsx

import React, { useState, useEffect } from 'react';
import { CheckCircle, Circle, Loader2, Clock, ChevronUp, ChevronDown, HelpCircle, ZapIcon } from 'lucide-react';

const AnalysisProgress = ({ 
  currentStep, 
  stepMessage, 
  steps, 
  progress, 
  startTime, 
  stepProgress = {}, 
  expandedStepId,
  onToggleExpand 
}) => {
  const [elapsedTime, setElapsedTime] = useState('0s');
  const [animatedSteps, setAnimatedSteps] = useState(new Set());

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

  // Track completed steps for animation
  useEffect(() => {
    if (currentStep > 0) {
      // When a step completes, add it to animated steps
      const previousStep = currentStep - 1;
      if (previousStep > 0 && !animatedSteps.has(previousStep)) {
        setAnimatedSteps(prev => new Set([...prev, previousStep]));
      }
    }
  }, [currentStep, animatedSteps]);

  // Helper to calculate step color based on status
  const getStepColor = (stepId) => {
    if (currentStep > stepId) return 'green'; // Completed
    if (currentStep === stepId) return 'blue'; // Active
    return 'gray'; // Pending
  };

  // Get completion percentage for a step
  const getStepPercentage = (stepId) => {
    if (currentStep > stepId) return 100; // Completed steps

    // For active steps
    if (currentStep === stepId) {
      // For section matching and impact analysis steps
      if (stepId === 4 || stepId === 5) {
        if (progress.total > 0) {
          return Math.round((progress.current / progress.total) * 100);
        }
        return Math.min(5, progress.percentage || 0);
      }

      // Check step-specific progress
      if (stepProgress[stepId]?.total > 0) {
        return Math.round((stepProgress[stepId].current / stepProgress[stepId].total) * 100);
      }

      return progress.percentage || 20; // Use global progress or default
    }

    return 0; // Pending steps
  };

  // Get step-specific progress data
  const getStepProgressData = (stepId) => {
    if (currentStep > stepId) {
      return { current: 100, total: 100, percentage: 100 };
    }
    if (currentStep === stepId) {
      return {
        current: progress.current || 0,
        total: progress.total || 0,
        percentage: progress.percentage || 0
      };
    }
    return { current: 0, total: 0, percentage: 0 };
  };

  // Helper function to render the progress indicator
  const renderProgressIndicator = (stepId) => {
    const color = getStepColor(stepId);
    const colorClasses = {
      green: 'bg-green-500',
      blue: 'bg-blue-600',
      gray: 'bg-gray-300 dark:bg-gray-600'
    };

    // Get step-specific progress data
    const stepData = getStepProgressData(stepId);
    const percentage = getStepPercentage(stepId);

    // Show detailed X/Y counter for section matching and impact analysis steps
    const showDetailedCounter = (stepId === 4 || stepId === 5) && 
                               (currentStep === stepId) && 
                               stepData?.total > 0;

    return (
      <div className="w-full space-y-1">
        {/* Show X/Y counter for specific steps */}
        {showDetailedCounter && (
          <div className="flex justify-between text-xs text-gray-600 dark:text-gray-400">
            <span>Progress: {stepData.current} of {stepData.total}</span>
            <span>{percentage}%</span>
          </div>
        )}

        {/* Progress bar */}
        <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-2">
          <div
            className={`${colorClasses[color]} h-2 rounded-full transition-all duration-500 ease-out`}
            style={{ width: `${percentage}%` }}
          />
        </div>
      </div>
    );
  };

  // Render a sparkle animation when a step completes
  const renderCompletionEffect = (stepId) => {
    if (!animatedSteps.has(stepId)) return null;

    return (
      <div className="absolute -top-1 -right-1 text-yellow-400 animate-ping-once">
        <ZapIcon className="w-5 h-5" />
      </div>
    );
  };

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

        {/* Overall progress indicator */}
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
            const isPending = !isActive && !isComplete;
            const isExpanded = expandedStepId === step.id;
            const stepPercentage = getStepPercentage(step.id);
            const stepData = getStepProgressData(step.id);

            // Define classes for different states
            const bgColorClasses = isActive 
              ? 'bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-800' 
              : isComplete 
                ? 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800' 
                : 'bg-gray-50 dark:bg-gray-900/20 border-gray-200 dark:border-gray-800';

            const textColorClasses = isActive 
              ? 'text-blue-600 dark:text-blue-400' 
              : isComplete 
                ? 'text-green-600 dark:text-green-400' 
                : 'text-gray-500 dark:text-gray-400';

            // Animation classes
            const animationClasses = isActive ? 'animate-pulse-subtle' : '';
            const transitionClasses = isComplete && animatedSteps.has(step.id) 
              ? 'transition-all duration-700 ease-bounce' 
              : 'transition-all duration-300';

            return (
              <li key={step.id} className="ml-6">
                {/* Step Icon */}
                <span className={`absolute flex items-center justify-center w-6 h-6 rounded-full -left-3 
                  ring-8 ring-white dark:ring-gray-800 ${transitionClasses}`}>
                  {isComplete ? (
                    <CheckCircle className="w-5 h-5 text-green-500" />
                  ) : isActive ? (
                    <Loader2 className="w-5 h-5 text-blue-500 animate-spin" />
                  ) : (
                    <Circle className="w-5 h-5 text-gray-400 dark:text-gray-600" />
                  )}
                </span>

                {/* Step Content Card */}
                <div 
                  className={`
                    p-4 rounded-lg border relative cursor-pointer
                    ${bgColorClasses} ${animationClasses} ${transitionClasses}
                    hover:shadow-md
                  `}
                  onClick={() => onToggleExpand(step.id)}
                >
                  {/* Step Header with Title and Percentage */}
                  <div className="flex justify-between items-center">
                    <h3 className={`font-medium ${textColorClasses}`}>
                      {step.name}
                    </h3>

                    <div className="flex items-center space-x-2">
                      {/* Only show percentage if the step is active or complete */}
                      {(isActive || isComplete) && (
                        <span className={`text-sm font-medium ${textColorClasses}`}>
                          {stepPercentage}%
                        </span>
                      )}

                      {/* Expand/Collapse icon */}
                      {isExpanded ? (
                        <ChevronUp className={`w-4 h-4 ${textColorClasses}`} />
                      ) : (
                        <ChevronDown className={`w-4 h-4 ${textColorClasses}`} />
                      )}
                    </div>
                  </div>

                  {/* Progress bar for all steps */}
                  {renderProgressIndicator(step.id, stepPercentage)}

                  {/* Step description - always visible */}
                  <p className="text-sm text-gray-600 dark:text-gray-300 mt-2">
                    {step.description}
                  </p>

                  {/* Expanded content */}
                  {isExpanded && (
                    <div className={`mt-3 pt-3 border-t border-gray-200 dark:border-gray-700 ${transitionClasses}`}>
                      {/* Step-specific content here */}
                      <div className="rounded-md bg-gray-100 dark:bg-gray-800 p-3 text-sm">
                        {isActive && (step.id === 4 || step.id === 5) && stepData.total > 0 ? (
                          <>
                            <div className="text-sm text-gray-600 dark:text-gray-300 mb-2">
                              {step.id === 4 && <span>Matching bill sections to digest items</span>}
                              {step.id === 5 && <span>Analyzing impacts on local agencies</span>}
                            </div>
                            <div className="text-sm text-gray-600 dark:text-gray-300 mb-1 flex justify-between">
                              <span>Processing {stepData.current} of {stepData.total}</span>
                              <span>{Math.round((stepData.current / stepData.total) * 100)}%</span>
                            </div>
                            <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-2">
                              <div
                                className="bg-blue-600 h-2 rounded-full transition-all duration-300"
                                style={{
                                  width: `${(stepData.current / stepData.total) * 100}%`,
                                }}
                              />
                            </div>
                            {/* Add estimated time remaining */}
                            <div className="text-xs text-gray-500 dark:text-gray-400 mt-2 italic">
                              {step.id === 4 && "This step typically takes 30-120 seconds depending on bill complexity"}
                              {step.id === 5 && "This step typically takes 60-180 seconds depending on bill complexity"}
                            </div>
                          </>
                        ) : isActive ? (
                          <div className="flex items-start text-blue-700 dark:text-blue-300">
                            <HelpCircle className="w-4 h-4 mr-2 mt-0.5 flex-shrink-0" />
                            <span>This step typically takes {
                              step.id === 1 ? "5-10 seconds" :
                              step.id === 2 ? "10-20 seconds" :
                              step.id === 3 ? "5-15 seconds" :
                              step.id === 4 ? "30-120 seconds" :
                              step.id === 5 ? "60-180 seconds" :
                              "15-30 seconds"
                            } to complete.</span>
                          </div>
                        ) : isComplete ? (
                          <div className="flex items-start text-green-700 dark:text-green-300">
                            <CheckCircle className="w-4 h-4 mr-2 mt-0.5 flex-shrink-0" />
                            <span>This step completed successfully.</span>
                          </div>
                        ) : (
                          <div className="flex items-start text-gray-500 dark:text-gray-400">
                            <Circle className="w-4 h-4 mr-2 mt-0.5 flex-shrink-0" />
                            <span>Waiting to start...</span>
                          </div>
                        )}
                      </div>
                    </div>
                  )}

                  {/* Completion effect */}
                  {renderCompletionEffect(step.id)}
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