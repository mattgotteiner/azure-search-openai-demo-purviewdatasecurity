import React from "react";
import { Icon, TooltipHost, ITooltipHostStyles } from "@fluentui/react";
import { SensitivityLabelInfo } from "../../api";
import styles from "./SensitivityBadge.module.css";

interface Props {
    label: SensitivityLabelInfo;
    showText?: boolean;
    size?: "small" | "medium" | "large";
}

export const SensitivityBadge: React.FC<Props> = ({ label, showText = true, size = "medium" }) => {
    const sizeClass = styles[size];
    const displayText = label.display_name || label.name;
    const badgeColor = label.color || "#6c757d"; // Use API color directly, fallback to gray

    const tooltipStyles: Partial<ITooltipHostStyles> = {
        root: { display: "inline-flex", alignItems: "center" }
    };

    const badgeContent = (
        <div
            className={`${styles.badge} ${sizeClass}`}
            style={{
                backgroundColor: badgeColor,
                color: "white",
                borderColor: badgeColor
            }}
        >
            <Icon iconName={label.icon} className={styles.icon} />
            {showText && <span className={styles.text}>{displayText}</span>}
        </div>
    );

    return (
        <TooltipHost content={`Sensitivity Label: ${displayText}`} styles={tooltipStyles}>
            {badgeContent}
        </TooltipHost>
    );
};
